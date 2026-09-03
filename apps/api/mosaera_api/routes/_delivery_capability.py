"""Can this project finish? — asked before the work, not after it (#120, ADR-0112).

F64 measured the shape this closes: the api-token bit that decides whether a project can
ever read as "Delivered" was invisible, so a stalled delivery and a missing credential
looked identical from the Delivery page. The delivery provider is the same bit one level
up — a GitHub-sourced project could never finish, and nothing said so until the operator
had done all the work and pressed the button.

**It informs; it never gates.** This endpoint decides nothing. The refusals it describes
are the ones ``delivery.py`` already returns; this only lets the page state them in
advance instead of surfacing them as a 400 at the finish line. No approval path, no
delivery-gate change (ADR-0102's spine is untouched).

The capability is DERIVED on every call from the project's source URL and its stored
credential bits. Nothing is persisted, so nothing can go stale.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from mosaera_connectors import detect_delivery_provider
from mosaera_core.config import Settings

from mosaera_api.app_context import AppContext
from mosaera_api.github_delivery import app_configured

# Why a project cannot deliver, and what the operator would do about it. Keyed by the
# reason the page shows; the wording is the operator's next action, not a diagnosis.
_GITLAB_NO_CREDENTIAL = (
    "This project has no GitLab token, so a merge request cannot be opened. "
    "Connect GitLab from the project's integration settings."
)
_GITHUB_UNCONFIGURED = (
    "This project's source is on GitHub, but this Mosaera instance has no GitHub App "
    "configured, so a pull request cannot be opened from here. An admin sets that up once "
    "in Settings."
)
_GITHUB_UNCONNECTED = (
    "This project's source is on GitHub. The Mosaera GitHub App is not installed on this "
    "repository yet, so a pull request cannot be opened from here."
)
_GITHUB_PRIVATE_NOTE = (
    "GitHub delivery currently covers public repositories: a private repository cannot be "
    "cloned yet, so a run would not start."
)
_UNKNOWN_HOST = (
    "This project's source is not on the configured GitLab and is not a recognized "
    "GitHub repository, so delivery has nowhere to open a request."
)
# task 4F (F8/F9/F10): the refusal above used to be a dead end — true, but naming no next step.
# `action` names the ONE thing that resolves it (publish this project to a remote); the web
# client renders it as a link rather than re-deriving when a refusal is actionable.
_PUBLISH_ACTION = {
    "label": "Publish this project to a remote",
    "pane": "integration",
}


def delivery_capability(detail: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """The capability record for one project. Pure — dict in, dict out.

    ``can_finish`` answers only "could a request be opened at all", which is the bit that
    was missing. It deliberately does NOT promise the delivery will succeed: an empty
    diff or a diverged base still refuse later, and claiming otherwise would replace one
    dishonest signal with a more confident one.
    """
    source = str(detail.get("source_repo") or "")
    provider = detect_delivery_provider(source, settings.gitlab_url)
    has_token = bool(detail.get("has_gitlab_token"))
    has_api_token = bool(detail.get("has_gitlab_api_token"))

    connected = bool(detail.get("has_github_connection"))
    configured = app_configured(settings)
    # Per-item requests are GitLab-only: its item MRs are STACKED (each targets its
    # predecessor), and reproducing that on a second forge is its own slice (ADR-0114). The
    # page reads this to withhold the per-item control rather than offer a failing one.
    item_requests = provider == "gitlab"
    note = ""

    if provider == "gitlab":
        can_finish = has_token
        reason = None if can_finish else "no_token"
        detail_text = "" if can_finish else _GITLAB_NO_CREDENTIAL
    elif provider == "github":
        note = _GITHUB_PRIVATE_NOTE
        if not configured:
            can_finish, reason, detail_text = False, "github_app_unconfigured", _GITHUB_UNCONFIGURED
        elif not connected:
            can_finish, reason, detail_text = False, "github_not_connected", _GITHUB_UNCONNECTED
        else:
            can_finish, reason, detail_text = True, None, ""
    else:
        can_finish, reason, detail_text = False, "not_gitlab", _UNKNOWN_HOST

    # Only the "not on any forge" refusal has a fix reachable from HERE — a missing GitLab
    # token or an uninstalled GitHub App are credential problems the delivery page already
    # names with their own remedy text; publishing solves a different problem (there is no
    # remote AT ALL) and only applies to that one reason.
    action = _PUBLISH_ACTION if reason == "not_gitlab" else None

    return {
        "provider": provider,
        "can_finish": can_finish,
        "reason": reason,
        "detail": detail_text,
        "action": action,
        # A limit that holds even when everything is connected — stated separately from
        # `detail`, which describes why a project CANNOT finish.
        "note": note,
        "item_requests_supported": item_requests,
        # The two GitLab credential bits, restated here so one call answers the whole
        # question for either provider. `merge_state_readable` is F64's own bit: without
        # `api` scope the MR poll never runs, so a project can open a merge request and
        # still never read as delivered. A connected GitHub project polls its PR with the
        # same installation token it pushes with, so the bit is simply true (ADR-0114).
        "has_gitlab_token": has_token,
        "has_gitlab_api_token": has_api_token,
        "github_app_configured": configured,
        "has_github_connection": connected,
        "merge_state_readable": (
            (provider == "gitlab" and has_api_token) or (provider == "github" and connected)
        ),
    }


def register_delivery_capability_routes(api: APIRouter, ctx: AppContext) -> None:
    @api.get("/projects/{project_id}/delivery/capability")
    def project_delivery_capability(project_id: str) -> dict[str, Any]:
        """What this project's delivery can and cannot do, before anything is attempted.

        Read-only, and gated by the middleware alone: it must be visible to exactly the
        people who can see the delivery controls, or the page would be back to offering a
        button whose refusal only the server knows about.
        """
        mem = ctx.require_memory()
        detail = mem.project_detail(project_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown project")
        return delivery_capability(detail, Settings.from_env())
