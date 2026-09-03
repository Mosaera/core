"""GitHub App auth (ADR-0114) — the JWT, the installation lookup, the scoped token.

The lookup tests are the security-relevant ones. Mosaera never reads an installation id out
of a redirect (GitHub documents that value as spoofable); it asks GitHub about the repository
the project already points at. These pin that the question asked is the right one.

Mirrors ``test_gitlab_write.py``'s urlopen-monkeypatch style.
"""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.parse
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from mosaera_connectors import github_app as ga

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()


class _Resp(io.BytesIO):
    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: Any) -> None:
        return None


def _capture(monkeypatch: pytest.MonkeyPatch, body: Any, status: int = 200) -> dict[str, Any]:
    """Record the request and return ``body``; mirrors test_gitlab_write's helper."""
    seen: dict[str, Any] = {}

    def fake_open(req: Any, timeout: float | None = None) -> Any:
        seen["method"] = req.method
        seen["url"] = req.full_url
        seen["headers"] = dict(req.headers)
        # Most calls here send JSON; the OAuth code exchange is form-encoded (GitHub's token
        # endpoint takes a form), so record whichever it is rather than assuming.
        if not req.data:
            seen["data"] = None
        else:
            try:
                seen["data"] = json.loads(req.data)
            except ValueError:
                seen["data"] = dict(urllib.parse.parse_qsl(req.data.decode()))
        seen["timeout"] = timeout
        if status >= 400:
            body_io = io.BytesIO(json.dumps(body).encode())
            # `{}` for headers, as test_gitlab_write.py does — HTTPError wants a Message.
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, body_io)  # type: ignore[arg-type]
        return _Resp(json.dumps(body).encode())

    monkeypatch.setattr(ga.urllib.request, "urlopen", fake_open)
    return seen


def _pad(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


# --- the JWT ---------------------------------------------------------------------


def test_jwt_claims_match_githubs_requirements() -> None:
    token = ga.app_jwt("12345", _PEM, now=1_000_000)
    header, payload, _ = token.split(".")
    assert json.loads(_pad(header)) == {"alg": "RS256", "typ": "JWT"}
    claims = json.loads(_pad(payload))
    assert claims["iss"] == "12345"
    assert claims["iat"] == 1_000_000 - 60, "iat must be back-dated for clock drift"
    assert claims["exp"] <= 1_000_000 + 600, "GitHub rejects exp more than 10 minutes out"
    assert claims["exp"] > 1_000_000


def test_the_signature_actually_verifies_against_the_public_key() -> None:
    """Not a shape check: a wrongly-signed JWT fails only at GitHub, as an opaque 401."""
    token = ga.app_jwt("12345", _PEM, now=1_000_000)
    signing_input, sig = token.rsplit(".", 1)
    _KEY.public_key().verify(
        _pad(sig), signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
    )


def test_a_malformed_key_fails_loudly_and_does_not_echo_the_key() -> None:
    with pytest.raises(ValueError) as exc:
        ga.app_jwt("1", "-----BEGIN PRIVATE KEY-----\nnot-a-key\n-----END PRIVATE KEY-----")
    assert "not-a-key" not in str(exc.value)
    assert "PEM" in str(exc.value)


def test_a_non_rsa_key_is_refused() -> None:
    from cryptography.hazmat.primitives.asymmetric import ed25519

    pem = (
        ed25519.Ed25519PrivateKey.generate()
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    with pytest.raises(ValueError, match="RSA"):
        ga.app_jwt("1", pem)


# --- the installation lookup (the anti-spoof core) -------------------------------


def test_installation_is_looked_up_by_repo_not_supplied_by_a_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _capture(monkeypatch, {"id": 42})
    ident, err = ga.installation_for_repo("https://api.github.com", "jwt-x", "owner/repo")
    assert (ident, err) == (42, None)
    assert seen["method"] == "GET"
    assert seen["url"] == "https://api.github.com/repos/owner/repo/installation"
    assert seen["headers"]["Authorization"] == "Bearer jwt-x"
    assert seen["headers"]["X-github-api-version"] == "2022-11-28"


def test_a_repo_without_the_app_installed_reports_the_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture(monkeypatch, {"message": "Not Found"}, status=404)
    ident, err = ga.installation_for_repo("https://api.github.com", "j", "owner/repo")
    assert ident is None
    assert err is not None and err.startswith("404")


def test_a_response_without_an_id_is_an_error_not_a_silent_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture(monkeypatch, {"unexpected": True})
    ident, err = ga.installation_for_repo("https://api.github.com", "j", "o/r")
    assert ident is None and err == "no installation id in the response"


# --- the minted token ------------------------------------------------------------


def test_the_token_is_scoped_to_one_repo_and_two_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Least privilege is the point: an installation may cover an entire org, and delivery
    needs one repo and two permissions."""
    seen = _capture(monkeypatch, {"token": "ghs_tok"})
    token, err = ga.mint_installation_token("https://api.github.com", "jwt-x", 42, repo="repo")
    assert (token, err) == ("ghs_tok", None)
    assert seen["method"] == "POST"
    assert seen["url"] == "https://api.github.com/app/installations/42/access_tokens"
    assert seen["data"] == {
        "repositories": ["repo"],
        "permissions": {"contents": "write", "pull_requests": "write"},
    }
    # The JWT authenticates the MINT; the minted token authenticates repository work.
    assert seen["headers"]["Authorization"] == "Bearer jwt-x"


def test_a_mint_failure_returns_an_error_and_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch, {"message": "Bad credentials"}, status=401)
    token, err = ga.mint_installation_token("https://api.github.com", "j", 1, repo="r")
    assert token is None and err is not None and err.startswith("401")


def test_every_call_is_bounded_by_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unbounded call holds a request worker forever; every GitLab counterpart is bounded."""
    seen = _capture(monkeypatch, {"id": 1})
    ga.installation_for_repo("https://api.github.com", "j", "o/r")
    assert seen["timeout"] == ga._TIMEOUT


def test_a_transport_failure_is_returned_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(req: Any, timeout: float | None = None) -> Any:
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(ga.urllib.request, "urlopen", boom)
    ident, err = ga.installation_for_repo("https://api.github.com", "j", "o/r")
    assert ident is None and err is not None and "no route" in err


# --- the installations listing ---------------------------------------------------


def test_the_listing_asks_the_app_endpoint_and_flattens_the_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _capture(
        monkeypatch,
        [
            {
                "id": 42,
                "repository_selection": "selected",
                "account": {"login": "acme", "type": "Organization", "avatar_url": "a.png"},
            }
        ],
    )
    rows, err = ga.list_installations("https://api.github.com", "j")
    assert err is None
    assert seen["method"] == "GET"
    # per_page=100, not GitHub's default 30: a truncated list rendered as complete is a count
    # that is quietly wrong (red-team round 2).
    assert seen["url"].endswith("/app/installations?per_page=100")
    assert rows == [
        {
            "id": 42,
            "account": "acme",
            "account_type": "Organization",
            "avatar_url": "a.png",
            "repository_selection": "selected",
        }
    ]


def test_an_app_installed_nowhere_is_an_empty_list_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordinary first-run answer. Reporting it as an error is what made the old GitHub
    panel read as a fault when nothing had gone wrong."""
    _capture(monkeypatch, [])
    rows, err = ga.list_installations("https://api.github.com", "j")
    assert rows == [] and err is None


def test_a_listing_failure_returns_a_scrubbed_error_and_no_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails closed to an empty list, and the message goes through the same
    ``scrub_credentials`` sink as every other exit in this module — so a URL-embedded
    credential cannot ride out on the error.

    Note the sink's actual contract: it strips ``user:secret@`` from http(s) URLs. It does
    NOT redact a bare token sitting loose in a response body — that has never been its
    promise, and GitHub does not echo the Authorization header back, so nothing here relies
    on it.
    """
    _capture(
        monkeypatch,
        {"message": "Bad credentials", "documentation_url": "https://u:ghs_SECRET@api.github.com"},
        status=401,
    )
    rows, err = ga.list_installations("https://api.github.com", "j")
    assert rows == []
    assert err is not None and err.startswith("401:")
    assert "ghs_SECRET" not in err


def test_an_unexpected_shape_is_an_error_rather_than_a_half_read_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture(monkeypatch, {"installations": []})
    rows, err = ga.list_installations("https://api.github.com", "j")
    assert rows == [] and err == "unexpected response shape from app/installations"


# --- the user grant + repo creation (ADR-0120) ------------------------------------


def test_the_code_exchange_posts_to_the_oauth_host_not_the_api_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _capture(monkeypatch, {"access_token": "ghu_TOKEN", "token_type": "bearer"})
    token, err = ga.exchange_user_code(
        "https://github.com",
        client_id="cid",
        client_secret="shh",
        code="abc",
        redirect_uri="https://mosaera.test/oauth/github/callback",
    )
    assert (token, err) == ("ghu_TOKEN", None)
    assert seen["url"] == "https://github.com/login/oauth/access_token"
    assert seen["headers"]["Accept"] == "application/json"
    # The secret goes in the POST body, server-to-server — never a query string.
    assert seen["data"]["client_secret"] == "shh"
    assert "client_secret" not in seen["url"]


def test_a_rejected_code_is_an_error_even_though_github_answers_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHub returns HTTP 200 with an `error` body for a bad code. Trusting the status alone
    would report a failed exchange as a success carrying no token."""
    _capture(
        monkeypatch,
        {"error": "bad_verification_code", "error_description": "The code passed is incorrect."},
    )
    token, err = ga.exchange_user_code(
        "https://github.com", client_id="c", client_secret="s", code="x", redirect_uri="r"
    )
    assert token is None
    assert err == "The code passed is incorrect."


def test_repo_creation_is_public_only_and_never_auto_inits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The visibility is not a parameter. A private repo cannot be cloned by this system yet
    (clone.py injects a credential only for the configured GitLab host), so creating one would
    hand the operator a repository whose runs can never start."""
    from mosaera_connectors import github_write as gw

    seen = _capture(monkeypatch, {"html_url": "https://github.com/me/widget", "name": "widget"})
    data, err = gw.create_public_repo("https://api.github.com", "ghu_TOKEN", "widget")
    assert err is None and data is not None
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/user/repos")
    assert seen["data"] == {
        "name": "widget",
        "private": False,
        "auto_init": False,
        "description": "",
    }
    assert seen["headers"]["Authorization"] == "Bearer ghu_TOKEN"


# --- the App manifest conversion (ADR-0121) --------------------------------------


def test_the_manifest_conversion_sends_no_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It is the one unauthenticated call in this module — the caller has no credential yet.
    An empty `Bearer ` is a malformed header, not an absent one."""
    seen = _capture(
        monkeypatch,
        {
            "id": 42,
            "slug": "mosaera",
            "pem": "-----PEM-----",
            "client_id": "Iv1",
            "client_secret": "s",
        },
    )
    data, err = ga.convert_manifest_code("https://api.github.com", "CODE")
    assert err is None and data is not None
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/app-manifests/CODE/conversions")
    assert "Authorization" not in seen["headers"]


def test_a_half_configured_app_is_refused_rather_than_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Storing an App without its private key would fail much later, at a connect, with an error
    pointing nowhere near this moment.

    `client_id`/`client_secret` are NOT required, though GitHub returns them: an App's OAuth pair
    is refused by the repository-creation endpoints, so nothing depends on their presence
    (ADR-0120 Amendment 2)."""
    _capture(monkeypatch, {"id": 42, "client_id": "Iv1", "client_secret": "s"})
    data, err = ga.convert_manifest_code("https://api.github.com", "CODE")
    assert data is None
    assert err is not None and "pem" in err


def test_an_app_without_an_oauth_pair_still_converts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing stored from the conversion needs them, so their absence is not a failure."""
    _capture(monkeypatch, {"id": 42, "pem": "-----PEM-----", "slug": "mosaera"})
    data, err = ga.convert_manifest_code("https://api.github.com", "CODE")
    assert err is None and data is not None and data["id"] == 42
