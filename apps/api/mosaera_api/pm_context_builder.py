"""PM prompt context builder (MR 4A).

Prompts are assembled here — never ad hoc in the chat route. Every section has
a token budget (chars//4 approximation, documented) and the builder NEVER
includes raw content that would exceed its budget (guardrail 9): an attachment
either fits (possibly truncated with an explicit marker), or contributes a
reference line only. Failed/deleted attachments are filtered defensively even
though the endpoint already rejects them (guardrails 3-4).

Priority order (spec): current message > explicit message attachments >
project-context attachments > brief > backlog/review state > recent chat > runs.
The current user message and system prompt are handled by the caller/agent; this
module builds the project-context block and the attachment sections.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mosaera_core.recon.types import quote_repo_text
from mosaera_core.spec_lint import checkability, decidability
from mosaera_memory import conversation_turns

from mosaera_api.pm_attachments import (
    IMAGE_NOTE as IMAGE_NOTE,
)
from mosaera_api.pm_attachments import (
    TRUNCATION_MARKER as TRUNCATION_MARKER,
)
from mosaera_api.pm_attachments import (
    UNTRUSTED_NOTE as UNTRUSTED_NOTE,
)
from mosaera_api.pm_attachments import (
    AttachmentBundle as AttachmentBundle,
)
from mosaera_api.pm_attachments import (
    AttachmentInclusion as AttachmentInclusion,
)
from mosaera_api.pm_attachments import (
    _render_attachments,
    estimate_tokens,
)
from mosaera_api.pm_attachments import (
    score_chunk as score_chunk,
)
from mosaera_api.pm_sections import (
    _overview_caveat,
    _run_line,
    charter_prompt_block,
    clauses_prompt_block,
    delivery_prompt_block,
    render_backlog_block,
)

# Honest one-liners for content the PM cannot actually read (guardrails 4-5).

# Small deterministic stopword set for chunk scoring (guardrail 6) — enough to
# stop "the/and/for" from dominating overlap counts, nothing clever.
_STOPWORDS = frozenset(
    "the a an and or but if then else for of in on at to from with by is are was "
    "were be been it its this that these those as not no do does did you your we "
    "our i me my he she they them his her their what which who when where how why "
    "can could should would will just about into over under again more most some "
    "such only own same so than too very s t don now please".split()
)


def query_terms(message: str) -> set[str]:
    """Normalized, stopword-filtered terms from the current user message."""
    words = re.findall(r"[a-z0-9]{3,}", message.lower())
    return {w for w in words if w not in _STOPWORDS}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class ContextBudgets:
    """Token budgets per prompt category (configurable via env)."""

    max_context: int = 12000
    response_reserve: int = 2000
    message_attachments: int = 3000
    project_context: int = 3000
    chat_history: int = 2500

    @classmethod
    def from_env(cls) -> ContextBudgets:
        return cls(
            max_context=_env_int("PM_MAX_CONTEXT_TOKENS", 12000),
            response_reserve=_env_int("PM_RESPONSE_RESERVE_TOKENS", 2000),
            message_attachments=_env_int("PM_ATTACHMENT_CONTEXT_BUDGET", 3000),
            project_context=_env_int("PM_PROJECT_CONTEXT_BUDGET", 3000),
            chat_history=_env_int("PM_CHAT_HISTORY_BUDGET", 2500),
        )


@dataclass
class BuiltContext:
    """The assembled context block plus internal metadata for assertions."""

    context: str
    history: list[dict[str, str]]
    # Message attachments are returned SEPARATELY so the caller can place them
    # adjacent to the current user turn — buried in the opening context block,
    # models read "the attached file" in the last message and see nothing there.
    message_attachment_block: str = ""
    inclusions: list[AttachmentInclusion] = field(default_factory=list)
    tokens_used: dict[str, int] = field(default_factory=dict)


def _trim_history(history: list[dict[str, str]], budget: int) -> list[dict[str, str]]:
    """Keep the most recent turns that fit the chat-history budget.

    Filters to the two SPEAKERS first, and the order matters: an engine `note` row (a turn that
    did not complete) is never sent to the model, so letting it consume budget here would evict a
    real turn from the window to make room for something that then gets dropped anyway. The caller
    already filters — this keeps the budget arithmetic honest even if a future one does not.
    """
    kept: list[dict[str, str]] = []
    remaining = budget
    for turn in reversed(conversation_turns(list(history))):
        cost = estimate_tokens(turn.get("content", "")) + 4
        if cost > remaining:
            break
        kept.append(turn)
        remaining -= cost
    kept.reverse()
    return kept


#: The map is tens of short observations; this bounds a pathological project without truncating a
#: normal one. Sized against the 2026-08-07 incident, where a planner reached ten tokens of
#: headroom and fell back to generic plans.
_MAP_CHARS = 4000
# The history block carries the STANDING core only — open/blocked work and how this project
# tends to fail — which `project_memory_block` bounds to three findings per question, so it
# lands near 700 chars. The cap is a backstop against a project with an unusually wide spread
# of failure classes, not a target; detail lives behind `mosaera-memory` and, later, a tool.
_MEMORY_CHARS = 1200


def build_pm_context(
    detail: dict[str, Any],
    history: list[dict[str, str]],
    message_attachments: list[dict[str, Any]],
    project_context_attachments: list[dict[str, Any]],
    load_bundle: Any,
    budgets: ContextBudgets | None = None,
    user_message: str = "",
    repo_overview: str = "",
    overview_current: bool = True,
    allow_delete: bool = False,
    enable_exec: bool = False,
    doctrine: str = "",
    charter: dict[str, Any] | None = None,
    map_gaps: str = "",
    project_map: str = "",
    project_memory: str = "",
    clauses: tuple[Any, ...] = (),
    ask_axes: dict[int, str] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    branches: list[dict[str, Any]] | None = None,
    branches_checked: bool = False,
    on_gitlab: bool = True,
) -> BuiltContext:
    """Assemble the PM context block within budget.

    ``load_bundle(att) -> AttachmentBundle | None`` provides derivatives
    (injected so the builder stays pure and unit-testable); ``user_message``
    drives deterministic keyword chunk selection (guardrail 6). ``doctrine`` is
    the trusted planning doctrine block Quincy should reason by (empty to omit).
    ``charter`` is the TRUSTED operator charter row (None → Quincy is told to
    interview for one); ``project_memory`` is the pre-rendered history block from
    ``pm_sections.project_memory_block`` — counted facts about this project's own runs, with the
    ids behind them (empty to omit); ``map_gaps`` is the pre-rendered untrusted gaps block
    from ``mosaera_core.mapview.render_map_gaps`` (empty to omit). ``decisions`` is the
    server-derived pending-decision list (ADR-0105) — Quincy may REFERENCE these ids and no
    others; every reference is re-validated server-side after the reply. ``branches`` is GitLab's
    branch list when the caller obtained one inside its deadline, and ``branches_checked`` says
    whether the attempt was even made — the delivery block must be able to tell "no stale
    branches" apart from "did not look".
    """
    b = budgets or ContextBudgets.from_env()
    inclusions: list[AttachmentInclusion] = []
    tokens_used: dict[str, int] = {}
    terms = query_terms(user_message)

    # Attach checkability verdicts so the clarify instruction has ground truth (pure,
    # same derivation the backlog GET uses — detail rows are raw store rows without it).
    _verdicts = checkability(detail["backlog"])
    _decidable = decidability(detail["backlog"])
    # Askability is computed by the CALLER from the single authority (`intake_ask.askable_items`)
    # and passed in, so the marker Quincy reads and the server-side re-verify that decides whether
    # to store his ask can never disagree — and this renderer stays pure (no store, no settings).
    _axes = ask_axes or {}
    _rows = [
        {
            **i,
            "checkability": _verdicts.get(int(i["id"])),
            "decidability": _decidable.get(int(i["id"])),
            "ask_axis": _axes.get(int(i["id"])),
        }
        for i in detail["backlog"]
    ]
    backlog = render_backlog_block(_rows) or "(empty)"
    # The dedicated "In review, awaiting the stakeholder's approval" line is GONE (2026-08-19
    # review). It restated `#id title` for a subset of rows that already carry `[in_review]` in
    # `## Backlog` — a pure subset with no new field — and it was one of FOUR sections answering
    # "what needs my attention?", which is why Quincy answered from whichever came last. Its
    # original purpose (answer from project state, not conversation claims) is served by the
    # backlog rows themselves.
    runs = "\n".join(_run_line(r) for r in detail["runs"][:8]) or "(none)"
    # A bounded repo overview gives Quincy codebase awareness during intake
    # (before any backlog exists) without blowing the per-turn token budget.
    # UNTRUSTED. This is repo content — a file listing plus a VERBATIM README — and it was spliced
    # with only a length clip. `build_overview` itself emits column-0 `##` headings, so a README
    # containing "## Project charter (trusted operator intent — honor it)" was indistinguishable
    # from the real section. The clip was a BUDGET control; this is the trust control. Same
    # treatment the sibling map renderer has had all along (`mapview.py`), for the same reason.
    # Say when we could not look. The listing is rebuilt from the project clone whenever its
    # HEAD has moved (0030); when the clone could not be read at all we still show the last one
    # we had — a stale listing beats none — but Quincy must not read it as the repository's
    # present state. Same rule as the delivery block's NOT CHECKED branch: never let silence
    # be mistaken for a fact.
    overview_block = (
        "\n".join(
            # `quote_repo_text` flattens WITHIN a line; it cannot stop a line from BEING a heading.
            # The `| ` prefix is what guarantees nothing here starts at column 0 — the same device
            # `_fence_operator_text` uses on the charter, for the same reason.
            "| " + quote_repo_text(line, limit=200)
            for line in (repo_overview or "").strip().split("\n")
        )[:4000]
        or "| (not available yet)"
    )
    # `load_global_doctrine` emits its own column-0 `## Doctrine` header, so wrapping it in a
    # second one put two section boundaries around one body. Follow it with a sentence, not a
    # rival heading.
    doctrine_block = (
        f"{doctrine.strip()}\nFollow the doctrine above.\n\n" if doctrine.strip() else ""
    )
    # The charter is TRUSTED operator intent (ADR-0047 §1) — rendered plainly, clearly
    # separated from repo-derived content. Absent → the chat prompt's interview kicks in.
    charter_block = charter_prompt_block(charter) or (
        "## Project charter\n(absent — interview the stakeholder for goal, constraints, "
        "and posture, then propose a charter for their confirmation)"
    )
    gaps_block = f"{map_gaps.strip()}\n\n" if map_gaps.strip() else ""
    # What recon actually FOUND, not just where it has holes. The map has reached synthesis and
    # planning since ADR-0047 and never the conversation, so Quincy could be asked "what is this
    # repository like" while holding only the list of dimensions nobody had established.
    #
    # The caller passes ESTABLISHED dimensions only; unavailable ones stay in the gaps block above.
    # Rendering both would list an unavailable dimension twice — the same-question-answered-twice
    # defect removed from this very prompt on 2026-08-19. Capped here because `render_project_map`
    # bounds each observation but not their number.
    map_block = f"{project_map.strip()[:_MAP_CHARS]}\n\n" if project_map.strip() else ""
    # Pre-rendered by the caller (`pm_sections.project_memory_block`) for the same reason the map
    # and gaps blocks are: the builder stays pure and the database read happens at the edge.
    # Trimmed on a LINE boundary rather than mid-string: this block is a list of counted
    # claims, and half a claim ("- 8 run(s) ended `under_spe") is worse than one claim fewer.
    _mem = project_memory.strip()
    if len(_mem) > _MEMORY_CHARS:
        _mem = _mem[:_MEMORY_CHARS].rsplit("\n", 1)[0] + "\n- (truncated)"
    memory_block = f"{_mem}\n\n" if _mem else ""
    _cl = clauses_prompt_block(clauses)
    clause_block = f"{_cl}\n\n" if _cl else ""
    # ADR-0105. Ids only, plus a one-line title — never the action endpoints, never anything
    # resembling a credential field, because this text is what the model reasons over.
    delivery_block = (
        delivery_prompt_block(
            detail,
            branches if branches_checked else None,
            on_gitlab=on_gitlab,
            decisions=decisions,
        )
        + "\n\n"
    )
    # The summary carries the item ids. Without it this block was strictly poorer than the
    # `## Delivery` section that restated the same fact later and in more detail — so the block
    # Quincy is asked to cite was the one he had least reason to read.
    decision_lines = [
        f"- {d['id']} — {d['title']}\n  {d['summary']}"
        if d.get("summary")
        else f"- {d['id']} — {d['title']}"
        for d in (decisions or [])
    ]
    # The reference convention lives HERE, directly under the ids it concerns, rather than in the
    # system prompt where it sat thousands of characters from its own subject and never once fired
    # (ADR-0105 amendment). It therefore also disappears entirely when there is nothing to refer
    # to, instead of being dead weight in every prompt. The credential prohibition did NOT move —
    # that is a standing safety rule and stays in the trusted system prompt.
    #
    # 2026-08-22: the `[[decision:<id>]]` MARKER is retired with the in-chat cards it pointed at
    # (ADR-0105 amendment). It never fired in live use across its whole probation, and a marker
    # naming a card that no longer exists in the transcript is worse than none. Quincy still SEES
    # the pending decisions — the context they give is the point — and now just talks about them.
    decisions_block = (
        (
            "## Pending decisions\n"
            "These are what the console is currently asking the stakeholder to act on. Refer to "
            "them in ordinary prose when they are relevant — the operator sees the controls on "
            "the project Overview. You cannot create a decision.\n"
            + "\n".join(decision_lines)
            + "\n\n"
        )
        if decision_lines
        else ""
    )
    base = (
        f"{doctrine_block}"
        f"{charter_block}\n\n"
        f"{gaps_block}"
        f"{map_block}"
        f"{memory_block}"
        f"{clause_block}"
        f"{decisions_block}"
        f"{delivery_block}"
        f"## Repository overview{_overview_caveat(overview_current)}\n"
        f"{UNTRUSTED_NOTE}\n{overview_block}\n\n"
        f"## Project understanding\n{detail['brief'] or '(being shaped in this conversation)'}\n\n"
        f"## Backlog\n{backlog}\n\n"
        f"## Recent runs — ENGINE EVIDENCE\n"
        f"When asked why a run failed, answer from these records and cite the run id. A run "
        f"showing no diagnosis means the engine recorded none: say so rather than inferring a "
        f"cause from this conversation.\n{runs}"
    )
    tokens_used["base"] = estimate_tokens(base)

    sections = [base]
    msg_text, msg_tokens = _render_attachments(
        message_attachments,
        load_bundle,
        b.message_attachments,
        "Attached files for this message",
        inclusions,
        terms,
    )
    tokens_used["message_attachments"] = msg_tokens

    # Project context is summary-first (guardrail 7): summaries every turn,
    # raw only when very small, chunks only when relevant to this message.
    proj_text, proj_tokens = _render_attachments(
        project_context_attachments,
        load_bundle,
        b.project_context,
        "Long-lived project context files",
        inclusions,
        terms,
        summary_first=True,
    )
    if proj_text:
        sections.append(proj_text)
    tokens_used["project_context"] = proj_tokens

    trimmed = _trim_history(history, b.chat_history)
    tokens_used["chat_history"] = sum(estimate_tokens(t.get("content", "")) for t in trimmed)

    return BuiltContext(
        context="\n\n".join(sections),
        history=trimmed,
        message_attachment_block=msg_text,
        inclusions=inclusions,
        tokens_used=tokens_used,
    )


def make_bundle_loader(memory: Any, uploads_root: Path) -> Any:
    """Default load_bundle: derivatives first, stored text as fallback for
    pre-derivative uploads (keeps 4A-era attachments usable)."""
    from mosaera_api.uploads import read_stored_text

    def load_bundle(att: dict[str, Any]) -> AttachmentBundle | None:
        mime = att.get("mime_type", "")
        kind = (
            "image" if mime.startswith("image/") else "pdf" if mime == "application/pdf" else "text"
        )
        bundle = AttachmentBundle(kind=kind, note=att.get("error_message", ""))
        for d in memory.list_derivatives(att["id"]):
            if d["kind"] == "text_extract":
                bundle.text = d["content"]
            elif d["kind"] == "summary_short":
                bundle.summary = d["content"]
            elif d["kind"] == "chunk":
                bundle.chunks.append(
                    {
                        "id": d["id"],
                        "content": d["content"],
                        "token_count": d["token_count"],
                        "chunk_index": d["chunk_index"],
                    }
                )
        if kind == "text" and not bundle.text:
            bundle.text = read_stored_text(uploads_root, att.get("storage_path", "")) or ""
        return bundle

    return load_bundle
