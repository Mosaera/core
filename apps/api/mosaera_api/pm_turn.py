"""One PM chat turn — assembling the context, calling Quincy, and persisting both sides.

Extracted from ``projects.py`` when that file reached the modularity ceiling. Cohesive by subject:
everything here serves a single conversational turn, whereas ``projects.py`` keeps the project
LIFECYCLE (intake, decompose, curation, changeset application).

Two rules this module exists to hold, both of which are controls rather than conveniences:

- **The model proposes; the server re-derives.** A charter, a clarification, and a decision
  reference are all validated here against real state before anything is returned — never believed
  because the reply said so (ADR-0080, ADR-0105).
- **Nothing here is authorized by the conversation.** A turn persists two messages and returns
  proposals. Every effect requires a separate, authenticated call to the endpoint that owns it.
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
from typing import Any

from mosaera_agents import pm
from mosaera_connectors import is_gitlab_source
from mosaera_core.clauses import load_clauses
from mosaera_core.config import Settings
from mosaera_core.doctrine import load_doctrine_topic, load_global_doctrine
from mosaera_core.intake_ask import askable_items
from mosaera_core.mapview import render_map_gaps, render_project_map
from mosaera_core.models import get_chat_model
from mosaera_core.tools.ledger import build_ledger_tools
from mosaera_core.tools.repo import describe_coder_capabilities
from mosaera_memory import NOTE_ROLE, MemoryStore, conversation_turns
from mosaera_memory.models_map import MAP_DIMENSIONS
from mosaera_policies import scoped_tools

from mosaera_api.decisions import project_decisions
from mosaera_api.pm_turn_parts import (
    _attach_evidence,
    _project_memory_block,
    _redacted_json,
)
from mosaera_api.projects import refresh_repo_overview
from mosaera_api.redact_chat import redact_secrets
from mosaera_api.routes._branch_guards import _rest_branches

#: How long a chat turn will wait on GitLab before answering without branch facts. Short on
#: purpose: the conversation must stay responsive when the instance is not.
CHAT_REST_DEADLINE_S = 3.0

_log = logging.getLogger(__name__)

_DECISION_REF = re.compile(r"\[\[decision:([A-Za-z0-9:_.-]{1,64})\]\]")


FAILURE_CAUSES: tuple[str, ...] = ("model_failed", "budget_exhausted", "empty")


# Reusing the planner's closed vocabulary verbatim
# (`mosaera_agents.pm._planning.fallback_reason`): budget_exhausted | model_failed | empty. Three
# strings, one meaning each, already pinned by test_pm_strip.py — a second vocabulary saying the
# same things differently is how two parts of a system start disagreeing about what happened.
#
# `budget_exhausted` is not reachable yet: nothing in the chat path has a step budget until the
# agent loop lands (slice 3 of docs/design/agentic-pm-chat.md). It is wired now so the loop
# inherits an honest failure path instead of retrofitting one.
def _failed_turn(
    memory: MemoryStore, project_id: str, sid: str | None, cause: str
) -> dict[str, Any]:
    """Record a turn that did not complete, and answer with the cause rather than a reply.

    Written as a `note` row, not a `pm` one. A failure is a fact about the engine; storing it as
    Quincy's speech gave it his avatar and his name, so the operator had to read the sentence
    carefully to notice that nothing had been answered — and it fed back into his own history as
    if he had said it. `conversation_turns` keeps it away from the model; the transcript endpoint
    still returns it, because the operator SHOULD be able to scroll back and see that a turn failed
    here.

    Persisted rather than response-local for the same reason the decision-marker strip runs before
    the write: the stored transcript is what a reload renders. A failure that vanishes on refresh
    did not happen, as far as the record is concerned.
    """
    # The row's body is the CAUSE TOKEN, not a sentence. RunDiagnosisCard's charter applied to the
    # transcript: "this card's charter is the exact record; the sentence is a reading, labeled as
    # such." Prose here would freeze today's wording into history and make the transcript a second
    # origin for operator language — so a copy fix would mean rewriting rows.
    with contextlib.suppress(Exception):
        memory.add_message(project_id, NOTE_ROLE, cause, session_id=sid)
    # No reply, no proposals: there is nothing to approve and nothing was changed. The words the
    # operator reads come from the copy deck (`apps/web/src/lib/plain.ts`) keyed by this cause.
    return {
        "reply": "",
        "changeset": [],
        "charter_proposal": None,
        "clarified_item": None,
        "decisions": [],
        "failure_cause": cause,
    }


def _tool_using_turn(
    memory: MemoryStore,
    project_id: str,
    settings: Settings,
    built: Any,
    model_text: str,
    capabilities: str,
    on_event: Any = None,
) -> tuple[str, list[dict[str, Any]], dict[str, str] | None, dict[str, Any] | None, str]:
    """One chat turn with the read-only ledger tool available (ADR-0111, off by default).

    The tools are built HERE, inside the enabled branch — never above it. If they were hoisted,
    the disabled path would pay the store reads too, and the two arms would differ in database
    traffic and latency even where the prompt matched. The point of the knob is a clean
    before-and-after; a shared side effect would spoil it.

    Scoped through the policy allowlist rather than passed straight in. `pm_chat` names exactly
    one tool, so this is where ADR-0111's split stops being prose: hand this function the whole
    toolset and the chat still gets only its ledger reads.
    """
    tools = scoped_tools("pm_chat", build_ledger_tools(memory, project_id))
    agent = pm.build_pm_agent(
        get_chat_model("pm", settings),
        tools,
        system_prompt=pm.chat_system_prompt(capabilities),
        step_limit=pm.CHAT_STEP_LIMIT,
    )
    outcome = pm.chat_with_agent(
        agent,
        built.context,
        built.history,
        model_text,
        on_event=on_event,
        # Only what he actually holds is reportable. A model asking for a tool it was never given
        # is not a lookup, and a record that counts one claims work that never happened.
        available=[tool.name for tool in tools],
    )
    return (*outcome[:4], outcome.failure)


def pm_chat(
    memory: MemoryStore,
    project_id: str,
    text: str,
    attachment_ids: list[str] | None = None,
    session_id: str | None = None,
    on_event: Any = None,
) -> dict[str, object]:
    """One PM chat turn; persists both turns (into ``session_id``) and any attachment links.

    Prompt assembly lives in pm_context_builder (budgeted, never ad hoc here).
    ``attachment_ids`` are pre-validated by the endpoint (ready + non-deleted). ``session_id``
    omitted → the project's current session (created on first send), so history is scoped to
    the thread while project knowledge (brief/backlog/runs/context) stays project-wide.
    """
    from mosaera_api.pm_context_builder import build_pm_context, make_bundle_loader

    settings = Settings.from_env()
    detail = memory.project_detail(project_id)
    if detail is None:
        return {"reply": "unknown project", "changeset": []}
    # Resolve the target thread once, so the history we read and both turns we write share it.
    sid = session_id or memory.ensure_default_pm_session(project_id)
    # Only what somebody SAID goes to the model: `note` rows record that a turn failed and are
    # for the operator's eyes (see `mosaera_memory.conversation_turns`).
    history = conversation_turns(memory.list_messages(project_id, sid))  # prior turns, THIS session
    message_id = memory.add_message(project_id, "user", redact_secrets(text), session_id=sid)
    if attachment_ids:
        memory.link_message_attachments(message_id, attachment_ids)

    message_atts = [
        a for att_id in (attachment_ids or []) if (a := memory.get_attachment(att_id)) is not None
    ]
    linked = {a["id"] for a in message_atts}
    # The ProjectContextItem registry decides what long-lived context exists
    # (guardrail 8: disabled items — scope changes, deletions — never appear).
    project_atts = [
        a
        for item in memory.list_project_context_items(project_id)
        if item["source_type"] == "attachment"
        and item["source_id"] not in linked
        and (a := memory.get_attachment(item["source_id"])) is not None
    ]
    # Charter (trusted) + map gaps (untrusted, rendered through the hardened boundary) feed
    # the intake interview (#42). Best-effort: a store without map/charter support (older
    # fakes, degraded memory) simply omits them.
    charter = None
    map_gaps = ""
    project_map = ""
    with contextlib.suppress(Exception):
        charter = memory.get_charter(project_id)
    with contextlib.suppress(Exception):
        dims = memory.list_map_dimensions(project_id)
        # Gaps = unavailable (stored) + never-established. Derived from the FULL dimension
        # set so an omitted dimension can never read as established by omission (#40 DEFER-a
        # doctrine); fingerprint-based staleness stays with the incremental-recon seam.
        missing = sorted(set(MAP_DIMENSIONS) - {str(d.get("dimension", "")) for d in dims})
        map_gaps = render_map_gaps(dims, missing)
        # Established dimensions only — the unavailable ones are the gaps block's job, and listing
        # them in both is the duplication this prompt was cleaned of on 2026-08-19.
        project_map = render_project_map(
            [d for d in dims if str(d.get("status") or "") in ("finding", "clean")]
        )
    # Attach each live item's evidence from the claim ledger. The ledger has always been queryable
    # only BY RUN, so "does every acceptance criterion have evidence?" — the question the North Star
    # names as Quincy's defining one — could be answered about an execution and never about a piece
    # of work. Reconciliation happens against the item's CURRENT acceptance, so a criterion added
    # since the last run reads as UNMEASURED rather than silently inheriting an old verdict.
    #
    # Best-effort and per item: a store without the accessor, or one bad row, must cost the operator
    # a marker rather than their conversation. Live items only — delivered work's bar is settled.
    _attach_evidence(memory, detail)
    # Loaded ONCE and used twice: to decide what may be asked about, and — new — to show Quincy
    # what has already been settled and why. Previously only their existence reached him.
    clauses = load_clauses(memory, project_id, enabled=settings.clauses_enabled)
    ask_axes = askable_items(
        detail.get("backlog") or [],
        clauses,
        decidability_asks=settings.intake_ask_undecidable,
        reachability_asks=settings.intake_ask_unreachable,
    )
    # A BOUNDED read, not a banned one. This path used to skip the REST-backed decision kind
    # entirely, on a 20-second worst case that was never observed — and the cost was that Quincy
    # could not see a decision the panel was showing him. With a tight deadline the common case
    # (a self-hosted GitLab, ~140ms) lands, and a slow one degrades to "not checked" instead of
    # holding up the conversation.
    pending = project_decisions(memory, settings, project_id, timeout=CHAT_REST_DEADLINE_S)
    # The same bounded read feeds the delivery block. `None` here is NOT "no branches" — it is
    # "did not look", and the renderer says so rather than letting Quincy infer a clean repo.
    #
    # Swallowed deliberately and narrowly: this is an ENRICHMENT on the interactive path, and no
    # failure of it — a store without the accessor, a TLS error, a malformed response — may cost
    # the operator their conversation. Every outcome lands on the one honest answer the renderer
    # already handles, so there is no silent second failure mode.
    try:
        branches = _rest_branches(
            memory,
            settings,
            project_id,
            str(detail.get("source_repo") or ""),
            timeout=CHAT_REST_DEADLINE_S,
        )
    except Exception:
        branches = None
    # Rebuilt when the project clone has moved (0030). Cheap: a HEAD-sha compare, and a tree
    # walk only on the turn after a delivery. `overview_current` is False only when the clone
    # could not be read at all, and the renderer then says so instead of passing off a stale
    # listing as the repository's current state.
    overview, overview_current = refresh_repo_overview(memory, settings, project_id)
    project_memory = _project_memory_block(memory, project_id)
    built = build_pm_context(
        detail,
        history,
        message_atts,
        project_atts,
        make_bundle_loader(memory, settings.uploads_dir),
        user_message=text,
        repo_overview=overview,
        overview_current=overview_current,
        allow_delete=settings.delete_tool_enabled,
        enable_exec=settings.coder_repl_enabled,
        doctrine=(
            # The authoring doctrine rides with the global block on the CHAT path, which is where
            # items get proposed and sharpened. It is trusted, small, and had never been loaded.
            (load_global_doctrine() + "\n\n" + load_doctrine_topic("acceptance_criteria")).strip()
            if settings.doctrine_enabled
            else ""
        ),
        charter=charter,
        map_gaps=map_gaps,
        project_map=project_map,
        project_memory=project_memory,
        clauses=clauses,
        ask_axes=ask_axes,
        decisions=pending,
        branches=branches,
        branches_checked=True,
        on_gitlab=is_gitlab_source(str(detail.get("source_repo") or ""), settings.gitlab_url),
    )
    # Attachment-only sends store an empty message (the transcript shows the
    # file card), but the model needs a real final turn to react to.
    model_text = text
    if not text.strip() and message_atts:
        names = ", ".join(a["filename"] for a in message_atts)
        model_text = f"(I attached {names} — please review and act on the file contents below.)"
    # Message-attachment content rides WITH the user's turn — adjacent, where
    # the model looks for "the attached file", not buried in the opening block.
    if built.message_attachment_block:
        model_text = f"{model_text}\n\n{built.message_attachment_block}"
    # pm_chat is the one interactive path that blocks a human synchronously on a
    # model call, so it's the path whose p50/p95 we track (#22, metric 3). Time
    # just the model call; recording is best-effort and never breaks the chat.
    _t0 = time.monotonic()
    cause = ""
    # The listener both forwards to whoever is watching and keeps a copy, so the same events that
    # drew the live status become the stored record. One source, so the two cannot disagree.
    steps: list[dict[str, Any]] = []

    def _record(kind: str, payload: dict[str, Any]) -> None:
        if kind == "step" and payload.get("kind"):
            steps.append(
                {
                    "kind": "tool",
                    "tool": str(payload.get("kind", "")),
                    "arg": str(payload.get("detail", "")),
                }
            )
        if on_event is not None:
            on_event(kind, payload)

    capabilities = describe_coder_capabilities(
        settings.delete_tool_enabled, settings.coder_repl_enabled
    )
    try:
        if settings.pm_chat_tools:
            reply, changeset, charter_proposal, clarification, cause = _tool_using_turn(
                memory, project_id, settings, built, model_text, capabilities, _record
            )
        else:
            reply, changeset, charter_proposal, clarification = pm.chat(
                get_chat_model("pm", settings),
                built.context,
                built.history,
                model_text,
                capabilities,
            )
    except Exception as exc:
        # `robust_invoke` RAISES a transport failure after its 3 attempts, and nothing above this
        # caught it: the turn became an unhandled 500, the operator saw the literal string
        # "500 Internal Server Error", and — because the user's message is persisted before the
        # model call — the thread was left with a dangling user turn and no reply row at all.
        #
        # Caught HERE and not inside `pm.chat`: an agents-layer function that swallowed transport
        # errors would hide them from every other caller, pmbench included. The API is where a
        # failure has to become a RECORD rather than a crash.
        _log.warning("pm chat turn failed for %s: %s", project_id, exc)
        reply, changeset, charter_proposal, clarification = "", [], None, None
        cause = "model_failed"
    _elapsed_ms = int((time.monotonic() - _t0) * 1000)
    if not cause and not reply and not changeset and not charter_proposal and not clarification:
        # F48: the turn produced nothing — no prose, no proposal. It used to be papered over with
        # "Here's what I'd suggest.", which reads as an answer and left the operator to notice the
        # emptiness themselves (seen ~5x in one thread, including on a direct actionable question).
        # Say so instead. Honest non-delivery is the same rule the run gate lives by.
        cause = "empty"
    if cause:
        # The note is NOT prose in Quincy's voice — the web renders the sentence from the cause
        # token, the same split RunDiagnosisCard uses ("every field is rendered exactly as the API
        # recorded it"). The stored body is a plain fallback for any reader that has only text.
        return _failed_turn(memory, project_id, sid, cause)
    # ADR-0105 amendment (2026-08-22): the `[[decision:<id>]]` reference channel is RETIRED. It
    # was placed on probation with an explicit kill criterion, never fired once in live use, and
    # the in-chat cards it pointed at moved to the Overview's "Waiting on you" band — a marker
    # naming a card that no longer exists in the transcript is worse than no marker.
    #
    # The STRIP stays and is not optional. Quincy still sees the pending decisions in context, so
    # it can still emit the old marker; and this runs BEFORE the message is persisted, because the
    # stored transcript is what a reload renders — stripping only the returned copy left raw
    # markers on screen the moment the operator refreshed, and fed them back into the model's
    # history every subsequent turn.
    reply = _DECISION_REF.sub("", reply).strip()
    pm_message_id = memory.add_message(project_id, "pm", redact_secrets(reply), session_id=sid)
    # What he looked up before answering, so a reload still shows it. Best-effort and suppressed:
    # a store one migration behind should cost the record of the lookups, never the answer — and
    # it means no test fake has to grow a method it does not care about.
    if steps:
        with contextlib.suppress(Exception):
            memory.add_message_steps(pm_message_id, steps)
    with contextlib.suppress(Exception):
        memory.record_latency_sample(project_id, "pm_chat", _elapsed_ms)
    # MR 4D: record what this reply actually used, straight from the builder's
    # inclusion metadata — the "Used context" chips are honest by construction.
    att_titles = {a["id"]: a["filename"] for a in [*message_atts, *project_atts]}
    sources: list[dict[str, object]] = []
    if detail["brief"]:
        sources.append({"source_type": "brief", "title": "Project understanding", "token_count": 0})
    if detail["backlog"]:
        sources.append({"source_type": "backlog", "title": "Backlog", "token_count": 0})
    for inc in built.inclusions:
        if inc.included_as == "skipped":
            continue
        sources.append(
            {
                "source_type": "attachment",
                "source_id": inc.attachment_id,
                "title": att_titles.get(inc.attachment_id, inc.filename),
                "included_as": inc.included_as,
                "token_count": inc.tokens_used,
            }
        )
    memory.add_message_context_sources(pm_message_id, sources)
    # Persist what Quincy PROPOSED so the card survives a reload (0031). Response-local state was
    # worse than a lost card: `pm.chat` strips the proposal out of the reply and substitutes
    # "Here's what I'd suggest.", so a refreshed transcript kept a sentence with nothing under it.
    #
    # Redacted on the way in, exactly like the reply above: a changeset op can quote the
    # conversation, and the ADR-0105 red team found a pasted credential stored verbatim and
    # replayed every turn. Best-effort — losing the card must never cost the operator the answer.
    #
    # Storing a proposal still grants it NOTHING: the trusted charter row is written exclusively by
    # the operator's admin-gated PUT (ADR-0047 §1: propose ≠ write), and a changeset is applied only
    # through the validator and the delivered-work guard.
    with contextlib.suppress(Exception):
        memory.add_message_proposals(
            pm_message_id,
            [
                {"kind": "changeset", "payload": _redacted_json(changeset)},
                {"kind": "charter", "payload": _redacted_json(charter_proposal)},
            ],
        )
    # Intake clarification (ADR-0080 §1): Quincy's ask is STORED ON THE ITEM (it must
    # survive reload — chat proposals are response-local) and only for an item that is genuinely
    # ASKABLE right now: the server re-derives the verdict rather than trusting the model, so a
    # model that raises an ask for a clean item — or one the operator already settled with a
    # ratified clause — is refused here. Best-effort: a bad fence/item never breaks the chat.
    stored_clarification = None
    if isinstance(clarification, dict):
        with contextlib.suppress(Exception):
            items = memory.list_backlog_items(project_id)
            askable = askable_items(
                items,
                load_clauses(memory, project_id, enabled=settings.clauses_enabled),
                decidability_asks=settings.intake_ask_undecidable,
                reachability_asks=settings.intake_ask_unreachable,
            )
            iid = int(clarification["item_id"])
            if iid in askable:
                memory.set_item_clarification(
                    iid,
                    claim_text=clarification["claim_text"],
                    why_unbindable=clarification.get("why", ""),
                    proposals=list(clarification.get("proposals") or []),
                    axis=str(askable[iid]),  # the marker that qualified it (ADR-0089)
                    proposal_kind="acceptance",  # the PM prompt's stated contract
                )
                stored_clarification = memory.get_backlog_item(iid)
    return {
        "reply": reply,
        "changeset": changeset,
        "charter_proposal": charter_proposal,
        "clarified_item": stored_clarification,
        "decisions": [],  # retired channel: nothing references a card any more
        # Empty means ANSWERED — the `PlanOutcome` shape, where a cause is set only on a failure.
        # A separate boolean would let "failed" and "why" drift apart.
        "failure_cause": "",
        "steps": steps,
    }
