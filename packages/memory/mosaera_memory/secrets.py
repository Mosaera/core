"""Envelope encryption for secrets at rest — GitLab project tokens and BYOM provider keys.

By default Mosaera stores these plaintext (a ``0600`` ``settings.json`` and a write-only DB
column). Set ``MOSAERA_SECRET_KEY`` — a Fernet key, generate one with
``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`` —
to encrypt them at rest (ADR-0039 / TM-0002):

- ``encrypt_secret`` returns a tagged ciphertext ``enc:v1:<fernet-token>``;
- ``decrypt_secret`` reverses it; an UNTAGGED value is treated as legacy plaintext and returned
  unchanged, so an existing install keeps working and its secrets migrate lazily on the next
  write (no batch migration);
- with **no key set**, both functions are the identity — nothing is encrypted (a one-time
  warning says so) and behaviour is exactly as before.

A value that is encrypted but whose key is missing or wrong raises ``SecretKeyError`` — loud, not
a silently-wrong token. Lives in the leaf ``mosaera_memory`` package so the store (DB token) and
core/api (provider keys) can both import it without violating the one-way layer graph.
"""

from __future__ import annotations

import os
import sys

from cryptography.fernet import Fernet, InvalidToken

_TAG = "enc:v1:"
_warned_plaintext = False


class SecretKeyError(RuntimeError):
    """A stored secret is encrypted but ``MOSAERA_SECRET_KEY`` is missing, malformed, or wrong."""


def _load_fernet() -> Fernet | None:
    """The configured Fernet, or None when no key is set. Raises ``SecretKeyError`` on a
    malformed key so a misconfiguration fails loudly instead of silently not encrypting."""
    raw = os.environ.get("MOSAERA_SECRET_KEY", "").strip()
    if not raw:
        return None
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError) as exc:
        raise SecretKeyError(
            "MOSAERA_SECRET_KEY is not a valid Fernet key (a 32-byte url-safe base64 string; "
            "generate one with Fernet.generate_key())"
        ) from exc


def is_encrypted(value: str) -> bool:
    """Whether ``value`` carries the ciphertext TAG. A prefix sniff only — a plaintext that happens
    to begin with ``enc:v1:`` also matches, so this is the fast classifier for read paths (decrypt /
    display); the WRITE path (`encrypt_secret`) additionally verifies the token actually decrypts so
    it never mis-encrypts tag-colliding plaintext (issue #33)."""
    return value.startswith(_TAG)


def _is_our_ciphertext(fernet: Fernet, value: str) -> bool:
    """True only for a value THIS module produced under ``fernet`` — tag-prefixed AND it actually
    decrypts. Distinguishes real ciphertext (leave it; encrypting is idempotent) from a PLAINTEXT
    that merely starts with the tag (``enc:v1:``), which a pure prefix sniff mis-reads as encrypted
    → passes through unchanged → later fails to decrypt (issue #33)."""
    try:
        fernet.decrypt(value[len(_TAG) :].encode())
        return True
    except (InvalidToken, ValueError):
        return False


def encrypt_secret(value: str | None) -> str:
    """Encrypt ``value`` for storage. Identity for an empty value or for a value that is GENUINELY
    already our ciphertext (idempotent — no double-encryption); identity (with a one-time warning)
    when no key is set — an install without ``MOSAERA_SECRET_KEY`` stores plaintext as before. A
    plaintext that merely starts with the ``enc:v1:`` tag is still encrypted, not mistaken for
    ciphertext (issue #33)."""
    global _warned_plaintext
    if not value:
        return ""
    fernet = _load_fernet()
    if fernet is None:
        # No key → identity. An already-tagged value passes through (it came from a keyed install);
        # fresh plaintext stays plaintext, with a one-time warning.
        if not is_encrypted(value) and not _warned_plaintext:
            _warned_plaintext = True
            print(
                "  WARNING: storing a secret in plaintext — set MOSAERA_SECRET_KEY (a Fernet "
                "key) to encrypt GitLab tokens and provider API keys at rest (ADR-0039).",
                file=sys.stderr,
            )
        return value
    # Key set → pass through ONLY genuine ciphertext (validated), so tag-colliding plaintext is
    # encrypted rather than mis-classified.
    if is_encrypted(value) and _is_our_ciphertext(fernet, value):
        return value
    return _TAG + fernet.encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str:
    """Reverse ``encrypt_secret``. An untagged value is legacy plaintext, returned unchanged. A
    tagged value needs the key that wrote it: a missing/wrong/malformed key raises
    ``SecretKeyError`` rather than returning a garbage token."""
    if not value or not is_encrypted(value):
        return value or ""
    fernet = _load_fernet()
    if fernet is None:
        raise SecretKeyError(
            "a stored secret is encrypted but MOSAERA_SECRET_KEY is not set — set the key it "
            "was encrypted with to decrypt it"
        )
    try:
        return fernet.decrypt(value[len(_TAG) :].encode()).decode()
    except InvalidToken as exc:
        raise SecretKeyError(
            "could not decrypt a stored secret — MOSAERA_SECRET_KEY does not match the key it "
            "was encrypted with"
        ) from exc


def try_decrypt(value: str | None) -> tuple[bool, str]:
    """Non-raising ``decrypt_secret`` for read/display paths. Returns ``(ok, plaintext)``:
    ``(True, "")`` for an absent secret, ``(True, plaintext)`` for legacy plaintext or a
    ciphertext the key opens, and ``(False, "")`` when a value is encrypted but the key is
    missing/wrong. Callers that only need to MASK or USE-or-skip a secret use this so a
    misconfigured ``MOSAERA_SECRET_KEY`` degrades one project instead of 500-ing a whole
    read path (the projects dashboard, ``Settings.from_env`` on every request, …)."""
    if not value:
        return True, ""
    try:
        return True, decrypt_secret(value)
    except (SecretKeyError, ValueError):
        # SecretKeyError = missing/wrong/malformed key. ValueError also covers a value that isn't
        # even UTF-8-encodable (e.g. a lone surrogate from a hand-corrupted settings.json reaching
        # `.encode()` before Fernet) — try_decrypt is the read-path safety net and must be TOTAL,
        # so ANY undecodable stored value degrades to "locked" rather than raising into a 500.
        return False, ""


def secret_status(value: str | None) -> str:
    """A safe-to-display classification of a stored secret WITHOUT exposing it: ``"absent"``
    (unset), ``"present"`` (set and readable), or ``"locked"`` (set but encrypted under a key we
    don't have). Lets summaries/lists show that a token exists without ever decrypting it."""
    if not value:
        return "absent"
    ok, _ = try_decrypt(value)
    return "present" if ok else "locked"


__all__ = [
    "SecretKeyError",
    "decrypt_secret",
    "encrypt_secret",
    "is_encrypted",
    "secret_status",
    "try_decrypt",
]
