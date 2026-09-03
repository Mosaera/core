"""GitHub App authentication — the App JWT, and the installation token it mints (ADR-0114).

Three calls, in the order the delivery path uses them:

1. ``app_jwt`` — a short-lived RS256 assertion proving we are the App. Never leaves this
   process and never authenticates a write; it exists only to ask GitHub two questions.
2. ``installation_for_repo`` — *which installation owns this repo?* This is the security
   core of the connect flow. GitHub's own setup-URL documentation says: "Bad actors can hit
   this URL with a spoofed ``installation_id``, so you should not rely on the validity of
   the ``installation_id`` parameter." So Mosaera never reads an installation id out of a
   redirect. It asks GitHub, about the repository the project already points at, and uses
   the answer. An attacker has nothing to supply.
3. ``mint_installation_token`` — the credential that actually pushes and opens the PR.
   Minted immediately before use, scoped to the ONE repository, with only the two
   permissions delivery needs. It lives an hour and is never stored.

Same defensive shape as ``gitlab_write._request``: bounded timeout, returns
``(value, error)``, never raises into the request, credentials scrubbed from error text.

The private key is the most sensitive value in this package. It is passed in, used to sign,
and never logged, never returned, and never placed in an error string.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mosaera_connectors.redact import scrub_credentials

_TIMEOUT = 20
_API_VERSION = "2022-11-28"

# GitHub rejects a JWT whose `exp` is more than 10 minutes out, and clock skew on the signing
# host is the classic cause of a "'Expiration time' claim ('exp') is too far in the future"
# 401 that looks like a bad key. Back-date `iat` by a minute, as GitHub's own examples do,
# and ask for well under the ceiling.
_JWT_BACKDATE = 60
_JWT_TTL = 540


def _b64(raw: bytes) -> str:
    """base64url without padding — the JWS encoding (RFC 7515 §2)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def app_jwt(app_id: str, private_key_pem: str, *, now: int | None = None) -> str:
    """A signed RS256 assertion identifying the App itself.

    ``iss`` is the App ID (GitHub also accepts the client id). ``now`` is injectable so the
    tests can pin the claims without freezing the clock globally.

    Raises ``ValueError`` on an unusable key — a malformed PEM is an operator configuration
    error that must surface loudly at connect time, not degrade into a confusing 401 later.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    issued = int(time.time()) if now is None else now
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {"iat": issued - _JWT_BACKDATE, "exp": issued + _JWT_TTL, "iss": str(app_id)}
    signing_input = (
        f"{_b64(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    ).encode("ascii")

    try:
        key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    except (ValueError, TypeError) as exc:
        # Deliberately does not echo the key material or the underlying message, which can
        # quote the input. The operator needs to know WHICH thing is wrong, not what we read.
        raise ValueError("the GitHub App private key is not a readable PEM private key") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("the GitHub App private key must be an RSA key (GitHub signs RS256)")

    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input.decode('ascii')}.{_b64(signature)}"


def _api(
    method: str,
    api_base: str,
    bearer: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = _TIMEOUT,
) -> tuple[Any, str | None]:
    """One GitHub REST call. Returns ``(data, None)`` or ``(None, error)`` — never raises."""
    url = f"{api_base.rstrip('/')}/{path.lstrip('/')}"
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _API_VERSION,
    }
    # The manifest conversion is the one UNAUTHENTICATED call here (the caller has no credential
    # yet — that is what it is fetching). Sending `Bearer ` with an empty value is a malformed
    # header, not an absent one, so omit it entirely rather than send an empty credential.
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310 — api.github.com
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read()
            return (json.loads(body) if body else None), None
    except urllib.error.HTTPError as exc:
        detail = scrub_credentials(exc.read().decode("utf-8", "replace")[:200])
        return None, f"{exc.code}: {detail}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, scrub_credentials(str(exc))


# F1/F2 (readiness review): the App-configured status bit was `bool(app_id and key)` — presence,
# never verified. `verify_app_credentials` is the cheapest authenticated call that proves BOTH the
# id and the private key actually work: sign a JWT, GET the one endpoint that identifies the App
# itself (no repository, no installation). 10s — this feeds an interactive status card, not
# delivery, and a slow/unreachable GitHub must not hang the page.
_VERIFY_TIMEOUT = 10


def verify_app_credentials(
    api_base: str, app_id: str, private_key_pem: str
) -> tuple[bool, str | None]:
    """Sign a JWT and ask GitHub who it identifies. ``(True, None)`` on success, ``(False, reason)``
    on a bad key, an unreachable host, or a rejected credential — never raises."""
    try:
        jwt = app_jwt(app_id, private_key_pem)
    except ValueError as exc:
        return False, str(exc)
    data, err = _api("GET", api_base, jwt, "app", timeout=_VERIFY_TIMEOUT)
    if err:
        return False, err
    if not isinstance(data, dict) or not data.get("id"):
        return False, "unexpected response from GitHub's /app endpoint"
    return True, None


def installation_for_repo(
    api_base: str, jwt: str, owner_repo: str
) -> tuple[int | None, str | None]:
    """Which installation of this App can reach ``owner_repo`` — asked of GitHub, never of the
    caller. See the module docstring for why this is the whole point.

    A 404 is the ordinary "the App is not installed on that repository" answer, not a fault;
    the caller turns it into an actionable message with the install link. Returns
    ``(installation_id, None)`` or ``(None, error)``.
    """
    data, err = _api("GET", api_base, jwt, f"repos/{owner_repo}/installation")
    if err:
        return None, err
    ident = data.get("id") if isinstance(data, dict) else None
    if not ident:
        return None, "no installation id in the response"
    return int(ident), None


def convert_manifest_code(api_base: str, code: str) -> tuple[dict[str, Any] | None, str | None]:
    """Turn a one-hour manifest code into a fully registered GitHub App (ADR-0121).

    This is the call that removes the setup form. GitHub's App-manifest flow lets an operator
    click once on github.com and hands back everything Mosaera needs in one response: ``id``,
    ``slug``, ``pem`` (the private key), ``client_id`` and ``client_secret``. Nothing is typed,
    nothing is copied between two browser tabs, and the values that matter never pass through a
    human clipboard.

    **Unauthenticated by design, and safe because the code is the secret.** There is no token to
    send — the caller has not got one yet, which is the point. The code is single-use, expires in
    an hour, and is worth nothing without the ``state`` this server minted and re-checks before
    getting here.
    """
    data, err = _api("POST", api_base, "", f"app-manifests/{code}/conversions")
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, "unexpected response shape from the manifest conversion"
    missing = [k for k in ("id", "pem") if not data.get(k)]
    if missing:
        # Fail loudly rather than store a half-configured App that fails later at connect time
        # with an error pointing nowhere near this moment. `client_id`/`client_secret` are NOT
        # required: GitHub returns them, but an App's OAuth pair cannot create repositories, so
        # nothing here depends on their presence (ADR-0120 Amendment 2).
        return None, f"the conversion response is missing {', '.join(missing)}"
    return data, None


def exchange_user_code(
    web_base: str,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> tuple[str | None, str | None]:
    """Exchange an authorization code for a **user** access token (ADR-0120).

    Why a user token exists here at all, when everything else in this module is an installation
    token: GitHub's repository-creation endpoints do not accept an installation token. Creating a
    repository is an act by a *person* on their own account, and GitHub models it that way. So
    this is the one credential Mosaera obtains on a user's behalf — used once, immediately, and
    discarded in the same request. Nothing persists it, exactly as ADR-0104 discards its GitLab
    grant.

    It posts to the OAuth host (``github.com``), not the API host — a different origin from every
    other call in this module, which is why it does not use ``_api``.

    GitHub answers a *failed* exchange with **HTTP 200** and an ``error`` field rather than a
    4xx. Reading only the status here would treat a rejected code as a successful one and hand
    back ``None`` as though it were a token, so the body is checked explicitly.
    """
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
    ).encode()
    req = urllib.request.Request(  # noqa: S310 — github.com over https
        f"{web_base.rstrip('/')}/login/oauth/access_token",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            payload = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = scrub_credentials(exc.read().decode("utf-8", "replace")[:200])
        return None, f"{exc.code}: {detail}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, scrub_credentials(str(exc))
    if not isinstance(payload, dict):
        return None, "unexpected response shape from the token exchange"
    if payload.get("error"):
        # `error_description` is GitHub's prose; the secret is never echoed, but scrub anyway
        # rather than rely on that staying true.
        return None, scrub_credentials(
            str(payload.get("error_description") or payload.get("error"))
        )
    token = payload.get("access_token")
    return (str(token), None) if token else (None, "no access_token in the exchange response")


def list_installations(api_base: str, jwt: str) -> tuple[list[dict[str, Any]], str | None]:
    """Every installation of this App, for the *settings* view only — never for delivery.

    Delivery still asks ``installation_for_repo`` about the one repository it is about to
    write to, because that question has no attacker-supplied input. This one answers a
    different, weaker question — "where is this App installed at all?" — so an operator
    staring at an empty page learns to install it rather than reading an error. Nothing here
    authorizes anything: the ids it returns are never spent, and the delivery path never
    reads them.

    Returns ``([], None)`` for an App installed nowhere — the ordinary first-run answer, and
    the caller renders it as a next step rather than a fault. On error, ``([], message)``.
    """
    # per_page=100 (GitHub's maximum; the default is 30). Without it an App installed on more
    # than 30 accounts returned a truncated list that the panel rendered as though it were
    # complete — a count that is quietly wrong is worse than one that is obviously missing
    # (red-team round 2). Beyond 100 this still truncates; nothing here is authorized on the
    # list, so the residual is a display limit, not an access one.
    data, err = _api("GET", api_base, jwt, "app/installations?per_page=100")
    if err:
        return [], err
    if not isinstance(data, list):
        return [], "unexpected response shape from app/installations"
    out: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        raw_account = row.get("account")
        account: dict[str, Any] = raw_account if isinstance(raw_account, dict) else {}
        out.append(
            {
                "id": row.get("id"),
                "account": account.get("login"),
                "account_type": account.get("type"),
                "avatar_url": account.get("avatar_url"),
                # "all" or "selected" — the difference between "every repo on this account"
                # and "the ones picked at install time", which is what an operator needs to
                # know before wondering why their repo is not covered.
                "repository_selection": row.get("repository_selection"),
            }
        )
    return out, None


def list_installation_repositories(
    api_base: str, jwt: str, installation_id: int
) -> tuple[list[dict[str, Any]], str | None]:
    """The repositories one installation can reach — read-only (task 4C settings panel).

    NOT used for delivery, same discipline as `list_installations`: nothing returned here is
    ever spent as authorization, so a forged/guessed installation id gains nothing — delivery
    still asks GitHub about the project's own `source_repo` via `resolve_installation`. This
    answers a narrower question — "which repos, if the operator is hunting for a URL to paste
    into New Project" — and stops at the first page (100, GitHub's max) for the same reason
    `list_installations` does: an unmarked truncation reads as a complete list, which is a
    worse failure than an obviously-capped one.

    GitHub's `GET /installation/repositories` listing is authenticated as the INSTALLATION, not
    the App — same "mint immediately before use" discipline as `access_for`'s per-delivery
    token, except this one is left unscoped (no `repositories` restriction) because the whole
    point is enumerating what the installation covers. It is never stored and never reused.
    """
    token, err = _api(
        "POST",
        api_base,
        jwt,
        f"app/installations/{installation_id}/access_tokens",
        {"permissions": {"metadata": "read"}},
    )
    if err:
        return [], err
    tok = token.get("token") if isinstance(token, dict) else None
    if not tok:
        return [], "no token in the installation-token response"
    data, err = _api("GET", api_base, str(tok), "installation/repositories?per_page=100")
    if err:
        return [], err
    repos = (data or {}).get("repositories") if isinstance(data, dict) else None
    if not isinstance(repos, list):
        return [], "unexpected response shape from installation repositories"
    out: list[dict[str, Any]] = []
    for row in repos:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "full_name": row.get("full_name"),
                "html_url": row.get("html_url"),
                "private": bool(row.get("private")),
            }
        )
    return out, None


def mint_installation_token(
    api_base: str, jwt: str, installation_id: int, *, repo: str
) -> tuple[str | None, str | None]:
    """Mint the 1-hour credential that pushes and opens the PR.

    Scoped down on purpose. ``repositories`` narrows the token to the single repo being
    delivered even when the installation covers many, and ``permissions`` asks for only what
    delivery needs — Contents to push, Pull requests to open. An installation token defaults
    to everything the installation was granted, which for a user who installed the App
    org-wide would be a far larger credential than this operation warrants.

    ``repo`` is the bare repository name (not ``owner/repo``) — that is the shape the
    ``repositories`` parameter takes.
    """
    data, err = _api(
        "POST",
        api_base,
        jwt,
        f"app/installations/{installation_id}/access_tokens",
        {
            "repositories": [repo],
            "permissions": {"contents": "write", "pull_requests": "write"},
        },
    )
    if err:
        return None, err
    token = data.get("token") if isinstance(data, dict) else None
    if not token:
        return None, "no token in the installation-token response"
    return str(token), None
