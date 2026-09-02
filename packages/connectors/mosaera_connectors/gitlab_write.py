"""GitLab REST WRITE client — MR create/edit + branch list (ADR-0103).

Kept SEPARATE from ``gitlab_client.py`` on purpose: that module's stated invariant is
"No writes to GitLab happen here." This module is the opposite trust posture — it performs
POST/PUT and reads that require the broader ``api`` scope — so an operator can tell at a
glance which credential each surface needs. It is used ONLY by operator-initiated MR
metadata calls; git transport (clone/push/delete) stays on the ``write_repository`` token
in ``gitlab.py``, and the autonomous sweep never touches this module.

Same defensive shape as ``gitlab_client._get``: bounded timeout, returns ``(data, error)``
never raises into the request, and scrubs credentials from any error text.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mosaera_connectors.redact import scrub_credentials

_TIMEOUT = 20


def _request(
    method: str,
    gitlab_url: str,
    token: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float | None = None,
) -> tuple[Any, str | None]:
    """One `api`-scoped REST call. Returns (data, None) or (None, error) — never raises.

    ``timeout`` lets a caller on a latency-sensitive path buy a *bounded* answer instead of
    choosing between a 20-second worst case and not asking at all. Exceeding it returns an error
    like any other failure, so every existing "cannot ask → claim nothing" path already handles it.
    """
    url = f"{gitlab_url.rstrip('/')}/api/v4/{path.lstrip('/')}"
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"PRIVATE-TOKEN": token}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310 — configured GitLab
    try:
        with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as resp:  # noqa: S310
            body = resp.read()
            return (json.loads(body) if body else None), None
    except urllib.error.HTTPError as exc:
        detail = scrub_credentials(exc.read().decode("utf-8", "replace")[:200])
        return None, f"{exc.code}: {detail}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, scrub_credentials(str(exc))


def _enc(project: str) -> str:
    return urllib.parse.quote(project, safe="")


def create_merge_request(
    gitlab_url: str,
    token: str,
    project: str,
    *,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
    squash: bool = False,
    remove_source_branch: bool = False,
    labels: list[str] | None = None,
) -> tuple[Any, str | None]:
    """POST a merge request with a FAITHFUL multi-line ``description`` (the push-option path
    cannot carry newlines). The branch must already be pushed. Returns the MR JSON or an error."""
    payload: dict[str, Any] = {
        "source_branch": source_branch,
        "target_branch": target_branch,
        "title": title,
        "description": description,
        "squash": squash,
        "remove_source_branch": remove_source_branch,
    }
    if labels:
        payload["labels"] = ",".join(labels)
    return _request("POST", gitlab_url, token, f"projects/{_enc(project)}/merge_requests", payload)


def update_merge_request(
    gitlab_url: str,
    token: str,
    project: str,
    iid: int,
    *,
    title: str | None = None,
    description: str | None = None,
    target_branch: str | None = None,
    squash: bool | None = None,
    remove_source_branch: bool | None = None,
    labels: list[str] | None = None,
    state_event: str | None = None,
) -> tuple[Any, str | None]:
    """PUT edits onto an existing MR (idempotent re-open of the compose form). Only the
    supplied fields are sent.

    ``state_event`` is GitLab's own lifecycle verb — ``close`` or ``reopen``. It rides this
    call rather than getting its own function because it is the same PUT on the same resource;
    callers are responsible for restricting it to those two values.
    """
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if description is not None:
        payload["description"] = description
    if target_branch is not None:
        payload["target_branch"] = target_branch
    if squash is not None:
        payload["squash"] = squash
    if remove_source_branch is not None:
        payload["remove_source_branch"] = remove_source_branch
    if labels is not None:
        payload["labels"] = ",".join(labels)
    if state_event is not None:
        payload["state_event"] = state_event
    return _request(
        "PUT", gitlab_url, token, f"projects/{_enc(project)}/merge_requests/{iid}", payload
    )


def merge_merge_request(
    gitlab_url: str,
    token: str,
    project: str,
    iid: int,
    *,
    when_pipeline_succeeds: bool = False,
    sha: str | None = None,
    squash: bool | None = None,
    remove_source_branch: bool | None = None,
) -> tuple[Any, str | None]:
    """Merge one MR — the only call in this codebase that changes the TARGET branch of a real
    repository (ADR-0102 amendment 2026-08-24).

    ``when_pipeline_succeeds`` is GitLab's own auto-merge: the same endpoint, deferred until CI
    goes green. It is offered when a running pipeline is the ONLY thing outstanding, because the
    alternative an operator has is to sit and watch the pipeline and click later — the same
    decision, made once instead of twice. It is NOT a way to merge past a red pipeline: GitLab
    still refuses if the pipeline fails.

    ``sha`` is the head the operator was shown. Passing it makes the merge FAIL rather than
    silently merge different code if the branch moved between the readiness read and the click —
    the same "evidence describes a tree" rule ADR-0108 applies to the gate, applied to the one
    action here that cannot be undone from this UI.

    Refusals come back as ``(None, "<code>: <detail>")`` like every other call in this module:
    409/405 for conflicts or an unmergeable state, 401/403 for a token without the rights, 404
    for an MR that is gone. Callers map those to named messages — never to "it didn't work".
    """
    payload: dict[str, Any] = {}
    if when_pipeline_succeeds:
        payload["merge_when_pipeline_succeeds"] = True
    if sha is not None:
        payload["sha"] = sha
    if squash is not None:
        payload["squash"] = squash
    if remove_source_branch is not None:
        payload["should_remove_source_branch"] = remove_source_branch
    return _request(
        "PUT", gitlab_url, token, f"projects/{_enc(project)}/merge_requests/{iid}/merge", payload
    )


def list_branches(
    gitlab_url: str, token: str, project: str, *, timeout: float | None = None
) -> tuple[Any, str | None]:
    """GET the project's branches (feeds the target-branch picker). Read needs `api`/`read_api`
    scope — it cannot ride the `write_repository` push token, so it lives here."""
    return _request(
        "GET",
        gitlab_url,
        token,
        f"projects/{_enc(project)}/repository/branches?per_page=100",
        timeout=timeout,
    )


# --- OAuth "Connect" (ADR-0104) ------------------------------------------------------------------
# Both calls DERIVE their host from ``gitlab_url`` (self-hosted first — gitlab.com is never
# hardcoded). Same defensive shape as ``_request``: bounded timeout, ``(data, error)``, never
# raises, credentials scrubbed from error text.


def _raw_post(
    url: str,
    *,
    form: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    bearer: str | None = None,
) -> tuple[Any, str | None]:
    """One POST to an arbitrary GitLab URL (used for the top-level ``/oauth/token`` endpoint and
    the Bearer-authed project-token mint, both outside the PRIVATE-TOKEN ``_request`` shape)."""
    headers: dict[str, str] = {}
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    else:
        data = json.dumps(json_body or {}).encode()
        headers["Content-Type"] = "application/json"
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")  # noqa: S310 — configured GitLab
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            body = resp.read()
            return (json.loads(body) if body else None), None
    except urllib.error.HTTPError as exc:
        detail = scrub_credentials(exc.read().decode("utf-8", "replace")[:200])
        return None, f"{exc.code}: {detail}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, scrub_credentials(str(exc))


def exchange_oauth_code(
    gitlab_url: str, *, client_id: str, client_secret: str, code: str, redirect_uri: str
) -> tuple[str | None, str | None]:
    """Exchange an authorization ``code`` for a user access token at ``{gitlab_url}/oauth/token``
    (the top-level OAuth endpoint, NOT ``/api/v4``). The client secret is sent server-to-server and
    never leaves this process. Returns ``(access_token, None)`` or ``(None, error)`` — the token is
    short-lived and used only to mint the project token, then discarded by the caller."""
    data, err = _raw_post(
        f"{gitlab_url.rstrip('/')}/oauth/token",
        form={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
    )
    if err:
        return None, err
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        return None, "no access_token in token response"
    return str(token), None


def create_project_access_token(
    gitlab_url: str,
    oauth_access_token: str,
    project: str,
    *,
    name: str,
    scopes: list[str],
    expires_at: str,
) -> tuple[str | None, str | None]:
    """Mint ONE project access token via ``POST /projects/:id/access_tokens``, authorized by the
    user's OAuth token (Bearer). ``expires_at`` is an ISO date (GitLab requires an expiry). Returns
    the minted token string or an error. The caller stores it as the project's git + api credential
    and discards the OAuth grant."""
    data, err = _raw_post(
        f"{gitlab_url.rstrip('/')}/api/v4/projects/{_enc(project)}/access_tokens",
        json_body={"name": name, "scopes": scopes, "expires_at": expires_at, "access_level": 40},
        bearer=oauth_access_token,
    )
    if err:
        return None, err
    token = data.get("token") if isinstance(data, dict) else None
    if not token:
        return None, "no token in project-access-token response"
    return str(token), None


def verify_oauth_client(gitlab_url: str, client_id: str, client_secret: str) -> tuple[bool, str]:
    """Probe whether ``client_id``/``client_secret`` actually authenticate against this GitLab —
    so a wrong secret is caught at config time, not at the first Connect. Uses the
    ``client_credentials`` grant (a pure app-credential check, no user/redirect needed): GitLab
    rejects bad app credentials with ``invalid_client``, the SAME error the authorization-code
    exchange raises. Returns ``(ok, detail)``:

    - ``(False, ...)`` ONLY on a definitive ``invalid_client`` — bad id/secret, reject the save.
    - ``(True, ...)`` otherwise: a 200 (verified), OR a non-auth error like ``unauthorized_client``
      / ``unsupported_grant_type`` (the client authenticated — that grant just isn't enabled — so
      the creds are valid for the auth-code flow we actually use), OR GitLab being unreachable
      (can't verify ⇒ don't block a save on a transient network fault). The detail reaches the UI.
    """
    _, err = _raw_post(
        f"{gitlab_url.rstrip('/')}/oauth/token",
        form={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    if err is None:
        return True, "verified with GitLab"
    if "invalid_client" in err:
        return False, (
            "GitLab rejected the Application ID or Secret (invalid_client). Check both, and that "
            "the OAuth application is registered on this GitLab instance."
        )
    # The client authenticated (the error is about the grant, not the credentials), or GitLab was
    # unreachable — either way don't block the save on it.
    return True, f"saved (could not fully verify: {err})"
