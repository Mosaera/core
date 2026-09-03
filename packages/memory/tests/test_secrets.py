"""Envelope encryption of secrets at rest (mosaera_memory.secrets, ADR-0039)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
from mosaera_memory import (
    decrypt_secret,
    encrypt_secret,
    is_encrypted,
    secret_status,
    try_decrypt,
)
from mosaera_memory.secrets import SecretKeyError


def test_roundtrip_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    ct = encrypt_secret("glpat-abcd1234")
    assert is_encrypted(ct) and ct != "glpat-abcd1234"  # tagged ciphertext, not the plaintext
    assert decrypt_secret(ct) == "glpat-abcd1234"


def test_encrypt_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    once = encrypt_secret("k")
    assert encrypt_secret(once) == once  # already-encrypted value is returned unchanged


def test_plaintext_starting_with_the_tag_still_roundtrips(monkeypatch: pytest.MonkeyPatch) -> None:
    # Issue #33: a PLAINTEXT that begins with the ciphertext tag (`enc:v1:`) must not be mistaken
    # for already-encrypted and passed through, then fail to decrypt. encrypt_secret checks it
    # that a tag-prefixed value genuinely decrypts before treating it as ciphertext.
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    for value in ("enc:v1:", "enc:v1:not-a-real-token", "enc:v1:glpat-abcd"):
        ct = encrypt_secret(value)
        assert ct != value  # it was actually encrypted, not passed through as fake ciphertext
        assert decrypt_secret(ct) == value  # and it roundtrips


def test_legacy_plaintext_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    # An untagged value predates encryption — decrypt returns it unchanged (lazy migration).
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    assert decrypt_secret("glpat-legacy") == "glpat-legacy"


def test_empty_and_none_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    assert encrypt_secret("") == "" and encrypt_secret(None) == ""
    assert decrypt_secret("") == "" and decrypt_secret(None) == ""


def test_no_key_is_plaintext_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without MOSAERA_SECRET_KEY, both are the identity — behaviour is exactly as before.
    monkeypatch.delenv("MOSAERA_SECRET_KEY", raising=False)
    assert encrypt_secret("k") == "k"
    assert decrypt_secret("plain") == "plain"


def test_encrypted_but_no_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    ct = encrypt_secret("secret")
    monkeypatch.delenv("MOSAERA_SECRET_KEY", raising=False)
    with pytest.raises(SecretKeyError, match="not set"):
        decrypt_secret(ct)


def test_wrong_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    ct = encrypt_secret("secret")
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())  # different key
    with pytest.raises(SecretKeyError, match="does not match"):
        decrypt_secret(ct)


def test_malformed_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_SECRET_KEY", "not-a-valid-fernet-key")
    with pytest.raises(SecretKeyError, match="valid Fernet key"):
        encrypt_secret("secret")


# --- non-raising read/display helpers (M-2): a misconfigured key degrades, never 500s ---


def test_try_decrypt_ok_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    assert try_decrypt("") == (True, "")  # absent
    assert try_decrypt("glpat-legacy") == (True, "glpat-legacy")  # legacy plaintext
    assert try_decrypt(encrypt_secret("secret")) == (True, "secret")  # decryptable ciphertext


def test_try_decrypt_locked_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # A value encrypted under a key we no longer have returns (False, "") instead of raising —
    # this is exactly what keeps the projects list / provider view / from_env from 500-ing.
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    ct = encrypt_secret("secret")
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())  # wrong key
    assert try_decrypt(ct) == (False, "")
    monkeypatch.delenv("MOSAERA_SECRET_KEY", raising=False)  # missing key
    assert try_decrypt(ct) == (False, "")


def test_secret_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    ct = encrypt_secret("secret")
    assert secret_status(None) == "absent"
    assert secret_status("") == "absent"
    assert secret_status("glpat-legacy") == "present"  # plaintext readable
    assert secret_status(ct) == "present"  # ciphertext the key opens
    monkeypatch.delenv("MOSAERA_SECRET_KEY", raising=False)
    assert secret_status(ct) == "locked"  # set but not decryptable


# --- property tests: prove the round-trip and the non-raising read helper are TOTAL (ADR-0041) ---


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())


# The key is deliberately CONSTANT across generated inputs (we vary the value, not the key), so
# the function-scoped-fixture health check does not apply — suppress it explicitly.
_KEYED = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])


@_KEYED
@given(value=st.text(min_size=1, alphabet=st.characters(codec="utf-8")))
def test_encrypt_decrypt_roundtrips_any_utf8_text(keyed: None, value: str) -> None:
    # decrypt_secret is a left inverse of encrypt_secret for ANY UTF-8-encodable text — no input
    # corrupts on the way through (the invariant a project token / provider key rides on). A real
    # secret is always UTF-8-encodable; the WRITE path never sees a lone surrogate.
    assert decrypt_secret(encrypt_secret(value)) == value


# Include the adversarial inputs st.text()'s default UTF-8 alphabet EXCLUDES — a lone surrogate,
# which `.encode()` chokes on with a UnicodeEncodeError (a ValueError, NOT a SecretKeyError). A
# hand-corrupted settings.json can hold exactly this, so try_decrypt must still not raise.
@_KEYED
@given(value=st.text(alphabet=st.characters()))
@example("\ud800")  # bare lone surrogate (untagged → passes through path)
@example("enc:v1:\ud800")  # tagged lone surrogate → hits decrypt_secret's .encode()
def test_try_decrypt_never_raises_keyed(keyed: None, value: str) -> None:
    # TOTALITY: try_decrypt returns (bool, str) for ANY input — legacy plaintext, real ciphertext,
    # a tagged-but-garbage value (bad base64, truncated token), or a non-UTF-8-encodable string.
    ok, out = try_decrypt(value)
    assert isinstance(ok, bool) and isinstance(out, str)


@given(value=st.text(alphabet=st.characters()))
@example("\ud800")
@example("enc:v1:\ud800")
def test_try_decrypt_never_raises_unkeyed(value: str) -> None:
    # Same totality with NO key set (the conftest strips MOSAERA_* per test): a tagged value now
    # takes the "key not set" branch, an untagged one passes through — neither may raise.
    ok, out = try_decrypt(value)
    assert isinstance(ok, bool) and isinstance(out, str)
