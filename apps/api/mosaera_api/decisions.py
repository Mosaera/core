"""What is waiting on a human for this project — derived, never stored (ADR-0105).

The chat becomes a SURFACE over controls that already exist; it never becomes a control. This
module answers "what decisions are pending?" by recomputing from live state on every call:

- **Derived, not stored.** No table, no migration, no second source of truth to drift. When the
  underlying control resolves, the decision stops being returned — there is no state to forget to
  clear, and nothing to reconcile.
- **Describes, never authorizes.** Each decision names the EXISTING endpoint its buttons call.
  Those endpoints keep their own auth, actor attribution, audit event, and (for a gate) the
  deterministic final authority. This list widens nobody's permissions; ``requires_admin`` is a
  presentation hint so the surface stops offering what the server would refuse, exactly as the
  project settings pane already does.
- **The model may reference, never mint.** ``visible_decision_ids`` is the allowlist a chat reply
  is filtered through, so a decision id Quincy invents renders nothing. Quincy's context carries
  untrusted repository content, so a model able to conjure a credential prompt would be a phishing
  primitive; the precondition is re-derived here rather than believed.

Naming: "card" already means *benchmark scorecard* throughout this repo. The server-side vocabulary
is **decision**; "card" stays a UI word.
"""

from __future__ import annotations

from typing import Any

from mosaera_connectors import is_gitlab_source
from mosaera_core.config import Settings
from mosaera_core.duplicates import duplicate_groups
from mosaera_core.reachability import reachability_findings
from mosaera_core.recon.types import quote_repo_text

from mosaera_api.routes._branch_guards import _rest_branches
from mosaera_api.routes.gitlab_status import gitlab_oauth_status

# The durable status a parked run carries (`store/_runs.py` writes uppercase).
_PARKED = "AWAITING_APPROVAL"


def _integration(detail: dict[str, Any], settings: Settings) -> dict[str, Any] | None:
    """The project cannot reach GitLab yet. Distinguishes the three states the operator would
    otherwise have to tell apart by reading two different settings pages."""
    if not is_gitlab_source(str(detail.get("source_repo") or ""), settings.gitlab_url):
        return None  # not a GitLab project: nothing to connect
    if detail.get("has_gitlab_token"):
        return None
    oauth = gitlab_oauth_status(settings)
    if oauth["oauth_env_pinned"] and not oauth["oauth_configured"]:
        return {
            "id": "integration:env-pinned",
            "kind": "integration_missing",
            "tier": "blocking",
            "state": "env_pinned",
            "title": "GitLab is configured in the environment",
            "summary": (
                "The OAuth application is pinned by environment variables, so it cannot be "
                "changed here. Edit the environment and restart."
            ),
            "requires_admin": True,
            "actions": [],
        }
    if not oauth["oauth_configured"]:
        return {
            "id": "integration:configure",
            "kind": "integration_missing",
            "tier": "blocking",
            "state": "configure",
            "title": "Connect GitLab to deliver this project",
            "summary": (
                "No GitLab application is registered yet. An admin registers one on the GitLab "
                "instance and enters its two values here — nothing can be pushed or merged until "
                "then."
            ),
            "requires_admin": True,
            # The credential POST is the EXISTING admin-gated route, which verifies the pair
            # against GitLab and encrypts the secret at rest (ADR-0039/0104). The secret never
            # travels the chat path and never enters the transcript.
            "actions": [{"label": "Set up GitLab", "kind": "gitlab_setup"}],
        }
    return {
        "id": "integration:connect",
        "kind": "integration_missing",
        # Blocking, like its two siblings: nothing about this project can be pushed or merged
        # until it is authorized. The key was MISSING here while both other branches set it —
        # `tier` is optional in the TS type, so the card happened to render as blocking by
        # default and the omission stayed invisible. A consumer that FILTERS on
        # `tier == "blocking"` would have silently dropped the most important card on a fresh
        # project. Found 2026-08-22 while building the Overview decision band.
        "tier": "blocking",
        "state": "connect",
        "title": "Authorize this project with GitLab",
        "summary": (
            "The GitLab application is ready. Authorizing mints this project's token — no "
            "credential to paste."
        ),
        "requires_admin": True,
        "actions": [{"label": "Connect", "kind": "oauth_start"}],
    }


def _parked_runs(detail: dict[str, Any], sessions: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Runs parked at a human gate.

    Read from the DURABLE run status, and only PEEK at a live session for the richer summary.
    Never calls ``get_session`` — that rehydrates, and resuming runs as a side effect of rendering
    a chat panel would make a read into a write.
    """
    out: list[dict[str, Any]] = []
    for run in detail.get("runs") or []:
        if str(run.get("status") or "").upper() != _PARKED:
            continue
        run_id = str(run["id"])
        summary = "This run is parked and waiting for your decision."
        session = (sessions or {}).get(run_id)
        interrupt = getattr(session, "pending_interrupt", None) if session is not None else None
        if isinstance(interrupt, dict):
            value = interrupt.get("value")
            if isinstance(value, dict) and value.get("question"):
                summary = str(value["question"])
        out.append(
            {
                "id": f"gate:{run_id}",
                "kind": "gate_pending",
                "tier": "blocking",
                "title": f"A run is waiting on you — {run.get('task') or run_id}"[:200],
                "summary": summary,
                "run_id": run_id,
                "requires_admin": False,
                # Answering goes through the run's own gate endpoint, which offers only the
                # answers the engine actually made available (ADR-0082 §1) and is the single
                # deterministic authority. The chat never decides anything itself.
                "actions": [{"label": "Open the gate", "kind": "open_run"}],
            }
        )
    return out


def _stuck_mrs(
    mem: Any,
    detail: dict[str, Any],
    settings: Settings,
    project_id: str,
    *,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """Item merge requests whose recorded target branch no longer exists — the case `retarget`
    exists to repair. Needs GitLab's branch list; when we cannot ask, we claim nothing rather
    than guess (the same degradation the Delivery page already accepts)."""
    items = [
        i
        for i in detail.get("backlog") or []
        if str(i.get("mr_state") or "") == "opened" and str(i.get("mr_target") or "")
    ]
    if not items:
        return []
    known = _rest_branches(
        mem, settings, project_id, str(detail.get("source_repo") or ""), timeout=timeout
    )
    if known is None:
        return []
    live = {str(b.get("name") or "") for b in known}
    out: list[dict[str, Any]] = []
    for i in items:
        target = str(i["mr_target"])
        if target in live:
            continue
        out.append(
            {
                "id": f"mr-stuck:{i['id']}",
                "kind": "mr_stuck",
                "tier": "blocking",
                "title": f"Item #{i['id']}'s merge request cannot merge",
                # The branch name is GitLab-derived — remote content that reaches both the model
                # context and the UI. Quote it like every other repo-derived string: flattened,
                # non-printables stripped, length-bounded, so it cannot forge a prompt section.
                "summary": (
                    f"It targets {quote_repo_text(target, limit=120)}, which no longer exists — "
                    "GitLab cannot merge it until it points somewhere real."
                ),
                "item_id": int(i["id"]),
                "requires_admin": False,
                "actions": [{"label": "Repoint it", "kind": "retarget"}],
            }
        )
    return out


def _delivered_without_mr(detail: dict[str, Any]) -> dict[str, Any] | None:
    """Items the product calls delivered that nothing is proposing anywhere.

    A run finished and its work is recorded, but there is no merge request — so the change exists
    only inside Mosaera. Measured on the live instance the day this was written: six items on one
    project and one on another, none of it visible to anyone.

    Free to derive (stored fields only), so it holds on the chat path as well as the panel. ONE
    aggregate decision, never one per item: six cards in a conversation is noise, not attention.
    """
    stranded = [
        i
        for i in detail.get("backlog") or []
        if str(i.get("status") or "") in ("in_review", "done") and not str(i.get("mr_url") or "")
    ]
    if not stranded:
        return None
    ids = ", ".join(f"#{i['id']}" for i in stranded[:6])
    more = f" and {len(stranded) - 6} more" if len(stranded) > 6 else ""
    n = len(stranded)
    return {
        "id": "delivered-no-mr",
        "kind": "delivered_no_mr",
        # STANDING, not blocking. The tiers describe the CONDITION, not the button (every card
        # links out): `blocking` means delivery cannot proceed until a human acts — a parked run,
        # a missing credential, a merge request that cannot merge. Nothing here is broken; work is
        # simply outstanding. Labelling that "waiting on you" turns a true statement into a banner
        # the operator learns to ignore — the performative-control failure this project keeps
        # hunting (red team 2026-08-19, finding 2, found by the owner clicking through).
        "tier": "standing",
        "title": (
            f"{n} delivered item{'s' if n != 1 else ''} "
            f"{'have' if n != 1 else 'has'} no merge request"
        ),
        "summary": (
            f"{ids}{more} — the work is recorded as delivered but nothing proposes it, so it is "
            "not visible to anyone outside Mosaera."
        ),
        "item_ids": [int(i["id"]) for i in stranded],
        # Opening a merge request is member-available: the authenticated call IS the control
        # (ADR-0102), so this needs no admin.
        "requires_admin": False,
        "actions": [{"label": "Review on the Delivery page", "kind": "open_delivery"}],
    }


#: Statuses a health finding may speak about: anything not yet delivered. `done`/`merged` work is
#: settled, and re-litigating it is how a report becomes noise.
_LIVE_STATUSES = frozenset({"todo", "in_progress", "deferred", "in_review"})


def _backlog_health(detail: dict[str, Any]) -> dict[str, Any] | None:
    """Backlog problems a deterministic check can see BEFORE a run is spent on them.

    Every input already existed and every one already ran somewhere; none of it reached the
    operator in time. On the LedgerCLI project the chain spent 310 model round trips across four
    consecutive runs, all ending INCOMPLETE, on items flagged by the checks below — a duplicate of
    already-delivered work, an item demanding a git operation no tool performs, an item whose
    acceptance nothing could check.

    **Checkability is deliberately absent.** Every backlog row in the PM context already carries
    `[checkability=UNDER_SPECIFIED — needs a clarify proposal]`, and the launch gate already
    refuses an item with an open ask. Repeating it here would be a second origin for one fact —
    the defect removed from this very prompt on 2026-08-19, where "what needs my attention?" was
    answered four times from four code paths and Quincy cited the weakest one. It would also fire
    on most real backlogs, making the card permanent furniture.

    ADVISORY on purpose. It reports; it never blocks a launch. `backlog_audit` is deliberately
    read-only for the same reason, and says why: three graders written during the 2026-08-05
    governance sweeps over-fired and scored correct work as failures, so an over-eager detector
    here would lock an operator's real backlog rather than merely produce a bad number.
    """
    items = [
        i for i in (detail.get("backlog") or []) if str(i.get("status") or "") in _LIVE_STATUSES
    ]
    if not items:
        return None

    groups = duplicate_groups(items)
    unbuildable = sorted(
        {
            f.item_id
            for f in reachability_findings(items, include_description=True, statuses=_LIVE_STATUSES)
        }
    )
    parts: list[str] = []
    if groups:
        # Show up to EIGHT groups, not four. Live on 2026-08-19 the backlog had exactly five and
        # the card hid one behind "(+1 more)" — a fifth of the finding, withheld to save a line.
        # A cap belongs here (a hundred groups is not a summary), but it should bind on the
        # pathological backlog, not the ordinary one.
        shown = 8
        rendered = "; ".join(", ".join(f"#{i}" for i in g) for g in groups[:shown])
        more = f" (+{len(groups) - shown} more)" if len(groups) > shown else ""
        parts.append(f"{len(groups)} group(s) look like the same work: {rendered}{more}")
    if unbuildable:
        ids = ", ".join(f"#{i}" for i in unbuildable[:6])
        parts.append(f"{ids} ask for something the delivery agent cannot do")
    if not parts:
        return None

    return {
        "id": "backlog-health",
        "kind": "backlog_health",
        # STANDING: nothing is broken and no run is blocked — these items simply should not be
        # started as written. Same reasoning as `delivered_no_mr`.
        "tier": "standing",
        "title": "Some backlog items would waste a run as written",
        "summary": ". ".join(parts) + ".",
        "item_ids": sorted({i for g in groups for i in g} | set(unbuildable)),
        # Curating the backlog is member-available; the changeset still needs approval to apply.
        "requires_admin": False,
        "actions": [{"label": "Review the backlog", "kind": "open_backlog"}],
    }


def project_decisions(
    mem: Any,
    settings: Settings,
    project_id: str,
    *,
    sessions: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """Every decision currently pending for this project, most blocking first.

    ``timeout`` bounds the one REST-backed kind (`mr_stuck`). The interactive chat turn passes a
    tight deadline; the endpoint takes the default. This replaced an outright BAN on the chat path,
    which was justified by a 20-second worst case that was never observed — measured against a
    self-hosted instance the whole derivation takes ~140ms — and whose real cost was that Quincy
    could not see a decision the panel was showing him. Exceeding the deadline is just another
    "cannot ask", so it lands on the existing claim-nothing path rather than a new failure mode.
    Note it bounds per-socket-operation IDLE time, not total wall clock: a peer that trickles can
    still outlast it. Accepted — the peer is the operator's own instance and the body is one page.
    """
    detail = mem.project_detail(project_id)
    if detail is None:
        return []
    out: list[dict[str, Any]] = []
    out.extend(_parked_runs(detail, sessions))
    integration = _integration(detail, settings)
    if integration is not None:
        out.append(integration)
    health = _backlog_health(detail)
    if health is not None:
        out.append(health)
    stranded = _delivered_without_mr(detail)
    if stranded is not None:
        out.append(stranded)
    out.extend(_stuck_mrs(mem, detail, settings, project_id, timeout=timeout))
    return out
