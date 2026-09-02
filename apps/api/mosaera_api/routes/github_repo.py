"""Create a project's GitHub repository by authorizing, not by pasting anything (ADR-0120).

**Why this exists at all, when ADR-0114 deliberately avoided a redirect.** ADR-0114 refused to
read an `installation_id` out of a redirect because GitHub documents that value as forgeable, and
because the question it answered ("which installation owns this repo?") could be asked of GitHub
directly instead. Neither escape applies here: creating a repository is an act by a *person* on
their own account, GitHub's creation endpoints do not accept an installation token, and no
server-side question can substitute for the user's consent. So this is a real OAuth handshake —
and it is built to ADR-0104's proven shape rather than a new one.

What is *not* trusted from the redirect, which is the whole design:

- **The repository name never crosses the wire.** It is derived server-side from the project's own
  name at callback time. There is no attacker-supplied name, no path, no owner — nothing to inject.
- **The state is spent before any code is exchanged** (single-use, TTL, bound to the initiating
  admin + project + provider), and the live session is re-checked against that binding.
- **The user token is discarded in the same request.** It creates the repository and is never
  stored, exactly as ADR-0104 discards its GitLab grant. Delivery continues to authenticate with
  installation tokens only, so the four-lane token-routing invariant (ADR-0114 §8) is unchanged.

Public repositories only, enforced in `github_write.create_public_repo` rather than described in a
doc: `clone.py::_auth_url` injects a credential only for the configured GitLab host, so a private
GitHub repo cannot be cloned and its runs would never start.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from mosaera_connectors import detect_delivery_provider
from mosaera_connectors import github as ghub
from mosaera_connectors import github_app as gapp
from mosaera_connectors import github_write as gwrite
from mosaera_core.config import Settings
from starlette.responses import RedirectResponse

from mosaera_api import github_delivery as ghd
from mosaera_api.auth import current_user

if TYPE_CHECKING:
    from mosaera_api.routes.context import AppContext

_PROVIDER = "github"
_STATE_TTL = timedelta(minutes=10)
_SCOPE = "public_repo"  # the narrowest scope that can create a PUBLIC repo; `repo` would also
# grant private access this flow has no use for.

_SLUG_STRIP = re.compile(r"[^A-Za-z0-9._-]+")


def repo_name_for(project_name: str, project_id: str) -> str:
    """A GitHub-legal repository name derived from the project's own name.

    Derived, never supplied: the operator picks a *project* name inside Mosaera, and this turns it
    into a repo name at callback time. That is what keeps the redirect free of anything worth
    forging — there is no name parameter to tamper with.

    GitHub accepts ``A-Za-z0-9._-``; every other run of characters collapses to a single dash. A
    name that reduces to nothing (or to bare dots, which GitHub rejects) falls back to the project
    id, so this always returns something creatable.
    """
    slug = _SLUG_STRIP.sub("-", (project_name or "").strip()).strip("-.")
    slug = slug[:90]
    return slug if slug.strip(".") else f"mosaera-{project_id[:12]}"


def _on_a_forge(settings: Settings, detail: dict) -> bool:
    """Whether this project's source is already a repository on a forge we deliver to.

    Deliberately not `bool(source_repo)`: a local path is a *source* but not a *repository*, and
    treating the two as the same is what made repository creation unreachable for every project
    that has code on disk — the case it exists for.
    """
    source = str(detail.get("source_repo") or "").strip()
    if not source:
        return False
    return detect_delivery_provider(source, settings.gitlab_url) in ("gitlab", "github")


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _redirect_uri(settings: Settings) -> str:
    return f"{settings.base_url}/oauth/github/callback"


def _configured(settings: Settings) -> bool:
    return bool(
        settings.github_oauth_client_id
        and settings.github_oauth_client_secret
        and settings.base_url
    )


def _fail(project_id: str | None, reason: str) -> RedirectResponse:
    """Land back on the pane that shows the outcome, with an honest error. Nothing is stored on
    any failure path.

    The target is a FIXED INTERNAL literal built from a project id we resolved ourselves — no part
    of it comes from the request, which is what keeps this from being an open redirect."""
    target = f"/projects/{project_id}/settings?pane=integration&" if project_id else "/projects?"
    return RedirectResponse(f"{target}repo_error={urllib.parse.quote(reason)}", status_code=302)


def make_github_repo_router(ctx: AppContext, require_admin: Callable[[Request], None]) -> APIRouter:
    api = APIRouter()

    @api.get("/github/repo/status")
    def github_repo_status(request: Request) -> dict[str, object]:
        """Whether "Create repository" can be offered at all, and to this caller."""
        settings = Settings.from_env()
        user = current_user(request, ctx.history)
        return {
            "configured": _configured(settings),
            "is_admin": bool(user and user.get("is_admin")),
            "host": urllib.parse.urlparse(settings.github_web_url).netloc or "github.com",
        }

    @api.get("/oauth/github/start")
    def github_repo_start(project_id: str, request: Request) -> RedirectResponse:
        # Admin-gated AND session-bound, like ADR-0104's start: this provisions a repository on
        # the operator's own account, so it needs a logged-in admin whose id the state binds to.
        # A header-only admin (service token) has no session to ride the redirect — refuse.
        require_admin(request)
        settings = Settings.from_env()
        if not _configured(settings):
            raise HTTPException(
                status_code=400,
                detail="GitHub repository creation is not configured on this instance "
                "(MOSAERA_GITHUB_OAUTH_CLIENT_ID / _SECRET / MOSAERA_BASE_URL). They come from "
                "the same GitHub App you registered for delivery.",
            )
        user = current_user(request, ctx.history)
        if user is None or not user.get("id"):
            raise HTTPException(
                status_code=400, detail="creating a repository requires a logged-in admin session"
            )
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        if _on_a_forge(settings, detail):
            # Creation is ONLY for a project that has no repository yet. Without this the
            # endpoint would repoint a WORKING project at a new empty repo and clear its
            # installation id — reachable by any admin, or by an admin following a crafted link,
            # with any project id. The UI already withholds the control; a rule that lives only
            # in the UI is not a control at all (red-team round 1).
            #
            # The test is "already on a forge", NOT "has any source at all". A project whose
            # source is a local path has no repository — it is exactly the case this exists for,
            # and the stricter test locked it out.
            raise HTTPException(
                status_code=400,
                detail="this project already has a repository; creation is only for a project "
                "whose source is not yet on GitHub or GitLab",
            )

        state = secrets.token_urlsafe(32)  # 256-bit; only its SHA-256 is stored
        mem.mint_oauth_state(
            _hash_state(state),
            int(user["id"]),
            project_id,
            _PROVIDER,
            datetime.now(UTC) + _STATE_TTL,
        )
        query = urllib.parse.urlencode(
            {
                "client_id": settings.github_oauth_client_id,
                "redirect_uri": _redirect_uri(settings),
                "state": state,
                "scope": _SCOPE,
            }
        )
        return RedirectResponse(
            f"{settings.github_web_url}/login/oauth/authorize?{query}", status_code=302
        )

    return api


def handle_github_repo_callback(ctx: AppContext, request: Request) -> RedirectResponse:
    """The pre-auth top-level callback. Registered outside ``/api`` so GitHub can reach it;
    its authorization is the spent state plus a live-session re-check."""
    settings = Settings.from_env()
    params = request.query_params
    if params.get("error"):
        return _fail(None, f"github: {params.get('error')}")
    code = params.get("code")
    state = params.get("state")
    if not code or not state:
        return _fail(None, "missing code or state")

    mem = ctx.history
    if mem is None:
        return _fail(None, "server has no store")

    # Spend the state FIRST — a replay, an expired state, or one minted for another provider
    # finds nothing and dies here, before any code is exchanged.
    binding = mem.spend_oauth_state(_hash_state(state), _PROVIDER, datetime.now(UTC))
    if binding is None:
        return _fail(None, "invalid or expired state")
    project_id = str(binding["project_id"])
    bound_user_id = int(binding["user_id"])

    user = current_user(request, ctx.history)
    if user is None or not user.get("is_admin") or int(user.get("id") or 0) != bound_user_id:
        return _fail(project_id, "session does not match the initiating admin")

    if not _configured(settings):
        return _fail(project_id, "repository creation is not configured")
    detail = mem.project_detail(project_id)
    if detail is None:
        return _fail(project_id, "unknown project")
    if _on_a_forge(settings, detail):
        # Re-checked here, not just at start: a state minted while the project had no repository
        # could be spent after one was set (a repo created in another tab, an intake that
        # finished mid-flow). Checking only at start leaves that window open.
        return _fail(project_id, "this project already has a repository")

    token, err = gapp.exchange_user_code(
        settings.github_web_url,
        client_id=str(settings.github_oauth_client_id),
        client_secret=str(settings.github_oauth_client_secret),
        code=code,
        redirect_uri=_redirect_uri(settings),
    )
    if err or not token:
        return _fail(project_id, f"authorization failed: {err or 'no token'}")

    # Server-derived name; nothing from the redirect reaches this call.
    name = repo_name_for(str(detail.get("name") or ""), project_id)
    created, err = gwrite.create_public_repo(
        settings.github_api_url,
        token,
        name,
        description="Created by Mosaera",
    )
    # The user token has done its job either way and is never stored — it goes out of scope here.
    if err or not created:
        # GitHub's own message is passed through verbatim (already credential-scrubbed). If it
        # rejects this token TYPE, that text is the evidence which settles it — a generic
        # "could not create" would hide exactly the fact worth learning.
        hint = ""
        if "not accessible by integration" in (err or ""):
            # GitHub's phrase for "this is an App token, and Apps may not do this". Naming the
            # remedy here is the difference between a dead end and a next step.
            hint = (
                " — repository creation needs an OAuth App, not the GitHub App; set one up in "
                "Settings → Git → GitHub"
            )
        return _fail(project_id, f"could not create the repository: {err or 'no repository'}{hint}")

    clone_url = str(created.get("clone_url") or created.get("html_url") or "")
    owner_repo = str(created.get("full_name") or "")

    # Push the project's existing history into the new repository BEFORE repointing it. An empty
    # repository that a project points at is worse than no repository: the next run clones
    # nothing. So this fails CLOSED — on a push failure the project keeps its current source and
    # the operator is told the repository exists but is empty, rather than being left with a
    # project that looks connected and cannot run.
    # The project's own working repository, NOT `source_repo`. That is where the agent's
    # committed work actually lives (`clone_project` keeps it across runs), and for a local-first
    # project `source_repo` is empty — there is no other candidate. It is also the more correct
    # source for an imported local path, whose working clone is ahead of the directory it came from.
    working = settings.projects_dir / project_id / "repo"
    if owner_repo and working.is_dir():
        branch, push_err = ghub.push_existing_repository(
            working, owner_repo=owner_repo, token=token
        )
        if push_err:
            return _fail(
                project_id,
                f"created {owner_repo} but could not push this project into it ({push_err}). "
                "The project still points at its current source; the empty repository is on "
                "GitHub and can be deleted there.",
            )
        _audit(ctx, project_id, user, f"{clone_url} (pushed {branch})")
    else:
        _audit(ctx, project_id, user, clone_url)

    mem.update_project(project_id, source_repo=clone_url)

    # Finish connected, rather than handing back a checklist. An installation covering the whole
    # account already covers a repository created a moment ago inside it, so asking the operator
    # to go and connect is asking them to confirm something already true — and it is the step most
    # likely to be skipped, leaving a project that looks published and cannot deliver.
    #
    # This is the SAME question the connect endpoint asks, with the same answer source: GitHub is
    # asked which installation owns this project's own `source_repo` (ADR-0114). Nothing is read
    # from the redirect, and a failure here is not a failure of the publish — the repository exists
    # and the code is in it, so it degrades to the manual step rather than undoing anything.
    connected = False
    if owner_repo:
        ident, _ = ghd.resolve_installation(mem, settings, project_id, owner_repo)
        connected = ident is not None

    return RedirectResponse(
        f"/projects/{project_id}/settings?pane=integration&repo=created"
        + ("&connected=1" if connected else ""),
        status_code=302,
    )


def _audit(ctx: AppContext, project_id: str, user: dict, clone_url: str) -> None:
    """Best-effort audit against the project's newest run — the anchor every other delivery
    route uses. Never fails the flow."""
    if ctx.history is None:
        return
    try:
        pdetail = ctx.history.project_detail(project_id)
        runs = (pdetail or {}).get("runs") or []
        if runs:
            ctx.history.add_audit_event(
                str(runs[0]["id"]),
                "project.github_repo_created",
                f"actor=user:{user.get('username')}; created {clone_url} (public)",
            )
    except Exception:  # noqa: S110 — audit is best-effort, never blocks the flow
        pass
