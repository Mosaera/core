"""One-click GitHub App registration via the manifest flow (ADR-0121).

This endpoint family hands out a manifest and receives an App private key + client secret, so the
tests are about who may do that and what is stored: the admin gate, the single-use state and its
session re-check, the least-privilege manifest, and the refusal to persist a half-configured App.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mosaera_api.routes import github_setup as ghs
from test_api import _client_with

_ADMIN = {"id": 7, "username": "admin", "is_admin": True}


class _Mem:
    def __init__(self, session: dict[str, Any] | None = None) -> None:
        self.session = session
        self.minted: list[dict[str, Any]] = []
        self._binding: dict[str, Any] | None = None

    def session_user(self, token_hash: str, now: Any) -> dict[str, Any] | None:
        return self.session

    def mint_oauth_state(
        self, state_hash: str, user_id: int, project_id: str, provider: str, expires_at: Any
    ) -> None:
        self.minted.append({"user_id": user_id, "project_id": project_id, "provider": provider})

    def set_binding(self, binding: dict[str, Any] | None) -> None:
        self._binding = binding

    def spend_oauth_state(self, state_hash: str, provider: str, now: Any) -> dict[str, Any] | None:
        # The real store matches on provider; mirror that, since a setup state being spendable by
        # the repo-creation callback (or the reverse) is exactly what must not happen.
        return self._binding if provider == "github-app-setup" else None


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MOSAERA_BASE_URL", "https://mosaera.example")
    # With no key, `encrypt_secret` is identity by design (a keyless install stores plaintext, as
    # it always has for gitlab_token). Set one so the at-rest assertion below tests encryption
    # rather than that default.
    from cryptography.fernet import Fernet

    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.chdir(tmp_path)


def _client(mem: _Mem) -> Any:
    c = _client_with(mem)
    c.cookies.set("mosaera_session", "cookie")
    return c


# ---- the manifest ----------------------------------------------------------------------


def test_the_manifest_asks_for_only_the_two_permissions_delivery_spends() -> None:
    """Least privilege declared at REGISTRATION. Asking for more and narrowing later would mean
    an over-broad App exists on the operator's account for the rest of its life."""
    from mosaera_core.config import Settings

    m = ghs.app_manifest(Settings.from_env({"MOSAERA_BASE_URL": "https://mosaera.example"}))
    assert m["default_permissions"] == {"contents": "write", "pull_requests": "write"}
    assert m["default_events"] == []
    assert m["public"] is False
    # The setup return leg and the user-authorization callback are DIFFERENT endpoints; the
    # manifest declares both, and conflating them breaks one flow silently.
    assert m["redirect_url"] == "https://mosaera.example/oauth/github/setup/callback"
    assert m["callback_urls"] == ["https://mosaera.example/oauth/github/callback"]


def test_manifest_endpoint_is_admin_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    mem = _Mem({"id": 9, "username": "member", "is_admin": False})
    assert _client(mem).get("/api/github/setup/manifest").status_code == 403
    assert mem.minted == []


def test_manifest_mints_a_bound_state_and_returns_nothing_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path)
    mem = _Mem(_ADMIN)
    r = _client(mem).get("/api/github/setup/manifest")
    assert r.status_code == 200
    body = r.json()
    assert body["url"].startswith("https://github.com/settings/apps/new?state=")
    json.loads(body["manifest"])  # a real manifest, not a string blob
    rec = mem.minted[0]
    assert rec["user_id"] == 7 and rec["provider"] == "github-app-setup"


def test_manifest_refuses_without_a_public_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """GitHub has to be told where to send the operator back; guessing it would produce an App
    whose redirect points somewhere unreachable."""
    monkeypatch.delenv("MOSAERA_BASE_URL", raising=False)
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    monkeypatch.chdir(tmp_path)
    r = _client(_Mem(_ADMIN)).get("/api/github/setup/manifest")
    assert r.status_code == 400 and "public URL" in r.json()["detail"]


# ---- the callback ----------------------------------------------------------------------


_FULL = {
    "id": 42,
    "slug": "mosaera",
    "pem": "-----PEM-----",
    "client_id": "Iv1.abc",
    "client_secret": "cs_secret",
}


def test_callback_stores_every_credential_the_app_returned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(ghs.gapp, "convert_manifest_code", lambda base, code: (_FULL, None))
    mem = _Mem(_ADMIN)
    mem.set_binding({"user_id": 7, "project_id": "", "provider": "github-app-setup"})

    r = _client(mem).get("/oauth/github/setup/callback?code=CODE&state=xyz", follow_redirects=False)
    assert r.headers["location"] == "/settings/git/github?setup=done"

    from mosaera_core.config import Settings

    stored = json.loads((Settings.from_env().home / "settings.json").read_text())
    assert stored["github_app_id"] == "42"
    assert stored["github_app_slug"] == "mosaera"
    # The private key goes through the encryption sink (ADR-0039) — never plaintext on disk.
    assert stored["github_app_private_key"] != "-----PEM-----"

    # The App's OAuth pair is returned by GitHub and deliberately NOT stored: an App token is
    # refused by the repository-creation endpoints (403 Resource not accessible by integration,
    # confirmed live). Storing it produced a configuration that read as complete and could not
    # work — so repository creation must still report itself unconfigured here.
    assert "github_oauth_client_id" not in stored
    assert "github_oauth_client_secret" not in stored
    assert "cs_secret" not in json.dumps(stored)


def test_callback_without_a_live_state_converts_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path)
    calls: list[str] = []

    def _convert(base: str, code: str) -> tuple[Any, str | None]:
        calls.append(code)
        return _FULL, None

    monkeypatch.setattr(ghs.gapp, "convert_manifest_code", _convert)
    mem = _Mem(_ADMIN)
    mem.set_binding(None)

    r = _client(mem).get("/oauth/github/setup/callback?code=CODE&state=xyz", follow_redirects=False)
    assert "setup_error=" in r.headers["location"]
    from mosaera_core.config import Settings

    assert calls == [], "a code must not be spent without a live state"
    assert not (Settings.from_env().home / "settings.json").exists()


def test_callback_refuses_a_session_that_is_not_the_initiating_admin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path)
    calls: list[str] = []

    def _convert(base: str, code: str) -> tuple[Any, str | None]:
        calls.append(code)
        return _FULL, None

    monkeypatch.setattr(ghs.gapp, "convert_manifest_code", _convert)
    mem = _Mem({"id": 99, "username": "other", "is_admin": True})
    mem.set_binding({"user_id": 7, "project_id": "", "provider": "github-app-setup"})

    r = _client(mem).get("/oauth/github/setup/callback?code=CODE&state=xyz", follow_redirects=False)
    assert "session" in r.headers["location"]
    assert calls == []


# ---- the manual escape hatch -----------------------------------------------------------


def test_manual_config_rejects_an_unusable_private_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Caught at the form, not at the first connect where it would read as a GitHub outage."""
    _configure(monkeypatch, tmp_path)
    r = _client(_Mem(_ADMIN)).post(
        "/api/github/setup/manual",
        json={"app_id": "42", "private_key": "not a pem", "slug": "mosaera"},
    )
    from mosaera_core.config import Settings

    assert r.status_code == 400 and "PEM" in r.json()["detail"]
    assert not (Settings.from_env().home / "settings.json").exists()


def test_manual_config_is_admin_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    mem = _Mem({"id": 9, "username": "member", "is_admin": False})
    r = _client(mem).post(
        "/api/github/setup/manual",
        json={"app_id": "42", "private_key": "-----PEM-----", "slug": "s"},
    )
    assert r.status_code == 403


# ---- the two bugs the first click found -------------------------------------------------


def test_the_csp_permits_posting_the_manifest_to_github() -> None:
    """`form-action 'self'` blocks a CROSS-ORIGIN form POST, and GitHub's manifest flow is
    exactly that. The browser refuses the navigation and reports only a console violation — so
    the button did nothing, visibly and silently. This is the regression guard for that.
    """
    from mosaera_api.security_headers import _csp

    policy = _csp(" https://github.com")
    assert "form-action 'self' https://github.com" in policy
    # The widening is for form submission ONLY — nothing else may name a remote host.
    for directive in ("script-src 'self'", "connect-src 'self'", "default-src 'self'"):
        assert directive in policy
    assert "unsafe-inline" not in policy.split("style-src")[0]


def test_setup_works_before_any_user_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """First run PRECEDES the first user, which is the whole point of first run. Requiring a
    session made the wizard unusable on exactly the instance it exists for."""
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    mem = _Mem(None)  # nobody logged in, no users configured
    r = _client(mem).get("/api/github/setup/manifest")
    assert r.status_code == 200
    assert mem.minted[0]["user_id"] == 0, "an absent identity is recorded as absent, not faked"


def test_a_state_minted_without_an_identity_is_not_asked_to_prove_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The callback must not demand a matching admin session for a flow started where there was
    no session to have — while still enforcing it wherever a real user did start one."""
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    monkeypatch.setattr(ghs.gapp, "convert_manifest_code", lambda base, code: (_FULL, None))
    mem = _Mem(None)
    mem.set_binding({"user_id": 0, "project_id": "", "provider": "github-app-setup"})

    r = _client(mem).get("/oauth/github/setup/callback?code=CODE&state=xyz", follow_redirects=False)
    assert r.headers["location"] == "/settings/git/github?setup=done"


# ---- the OAuth App that creates repositories (ADR-0120 Amendment 2) --------------------


def test_the_oauth_app_is_stored_separately_and_its_secret_encrypted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Repository creation needs an OAuth App because GitHub refuses App tokens there. It is a
    distinct credential with a distinct setup, not a by-product of registering the App."""
    _configure(monkeypatch, tmp_path)
    r = _client(_Mem(_ADMIN)).post(
        "/api/github/oauth-app", json={"client_id": "Ov23li.x", "client_secret": "shhh"}
    )
    assert r.status_code == 200

    from mosaera_core.config import Settings

    stored = json.loads((Settings.from_env().home / "settings.json").read_text())
    assert stored["github_oauth_client_id"] == "Ov23li.x"
    assert stored["github_oauth_client_secret"] != "shhh"
    assert "shhh" not in json.dumps(stored)


def test_the_oauth_app_endpoint_is_admin_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path)
    mem = _Mem({"id": 9, "username": "member", "is_admin": False})
    r = _client(mem).post("/api/github/oauth-app", json={"client_id": "c", "client_secret": "s"})
    assert r.status_code == 403
