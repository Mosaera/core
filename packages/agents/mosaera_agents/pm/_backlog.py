"""PM backlog & chat: understanding, decomposition, curation, chat, summaries."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from mosaera_core.task_spec import acceptance_text

from mosaera_agents.messages import message_text
from mosaera_agents.pm._chat_agent import replay
from mosaera_agents.pm._chat_prompt import _CHANGESET_OPS, _CHAT_SYSTEM
from mosaera_agents.pm._proposals import (
    _CHARTER_BLOCK,
    _CLARIFY_BLOCK,
    _JSON_BLOCK,
    _extract_changeset,
    _extract_charter,
    _extract_clarify,
)
from mosaera_agents.prompts import PM_CAPABILITIES
from mosaera_agents.retry import robust_invoke

_FALLBACK_BRIEF = (
    "## Goals\n(Describe the outcome.)\n\n## Requirements\n- \n\n"
    "## Deliverables\n- \n\n## Acceptance criteria\n- "
)


_UNDERSTANDING_SYSTEM = (
    PM_CAPABILITIES + "\n\n"
    "You are a technical project manager initializing a software project. From the repository "
    "overview and your intake conversation with the stakeholder, write a concise **Project "
    "Understanding** in markdown with these sections: `## Goals`, `## Requirements`, "
    "`## Deliverables`, `## Acceptance criteria`. Ground it in the actual repository and what the "
    "stakeholder actually asked for in the conversation. Keep it tight and reviewable. Do not "
    "write code and do not include a plan of implementation steps."
)

# Role-specific instructions for HOW each PM prompt should use the injected coder
# capability block. Appended (with the block) only when a capability string is
# supplied, so direct callers without one keep the original behavior.
_DECOMPOSE_CAPABILITY_CLAUSE = (
    "Propose ONLY items the delivery agent can build with the tools above. Do NOT create a "
    "backlog item for work that needs an action it does not have (e.g. deleting/renaming/moving "
    "files, git or shell commands, migrations, installs) — silently omit such work from the JSON "
    "array; it is captured for the stakeholder in the brief's manual-steps section instead."
)
_CURATE_CAPABILITY_CLAUSE = (
    "Propose ONLY work the delivery agent can build with the tools above. An `add` or `split` op "
    "that needs an action it does not have (deleting/renaming/moving files, git or shell commands, "
    "migrations, installs) is unbuildable — do not create it. If existing work depends on such an "
    "action, say so in the op's `why` rather than proposing an item that cannot be delivered."
)
_UNDERSTANDING_CAPABILITY_CLAUSE = (
    "If the stakeholder needs anything the delivery agent cannot do with the tools above, do not "
    "silently drop it: after the four sections, add a final "
    "`## Manual steps (outside the delivery agent's capability)` section listing each such item "
    "with concrete, honest steps the stakeholder can perform themselves (e.g. the exact git "
    "commands). Omit that section entirely when everything is within capability."
)
# The first sentence is stated for the CHAT only. The planner genuinely holds read tools, so
# telling IT the list is not its own would be false — which is why this lives in the chat clause
# and not in the shared capability block.
#
# Why it has to be said at all: `render_capabilities` is positive-only and records the reasoning —
# "the negative (what the agent CANNOT do) is implied by absence". Absence is not something a
# model reliably infers. Asked live on 2026-08-24 what he could call, Quincy listed `list_files`,
# `read_file`, `search`, `edit_file`, `write_file`, `run_tests` and `sandbox_exec` beside the one
# tool he actually held — and reached for `search` instead of it. Nothing was bound so nothing
# ran, but a PM who believes he can write files will tell a stakeholder so.
_CHAT_CAPABILITY_CLAUSE = (
    "Those are the DELIVERY AGENT's tools, not yours: you cannot call any of them yourself, and "
    "must never say or imply that you will. The only tools YOU can call are the ones offered to "
    "you directly in this conversation — if none are offered, you have none. "
    "Never propose (in the JSON block) an item the delivery agent cannot build with the tools "
    "above. If the stakeholder asks for out-of-capability work (e.g. deleting a file, running "
    "git), say plainly that we can't do this currently and give the exact manual steps to do it "
    "themselves in prose — do not turn it into a proposal."
)


def _augment_system(base: str, capabilities: str, clause: str) -> str:
    """Fold the live coder-capability block + a role-specific instruction into a
    system prompt. No-op when ``capabilities`` is empty so direct callers that do
    not supply one keep the original prompt verbatim."""
    if not capabilities.strip():
        return base
    return f"{base}\n\n## Delivery agent capabilities\n{capabilities}\n\n{clause}"


def synthesize_understanding(
    model: BaseChatModel,
    messages: Sequence[dict[str, str]],
    repo_overview: str,
    capabilities: str = "",
    doctrine: str = "",
    charter_block: str = "",
    map_block: str = "",
) -> str:
    """Synthesize the project understanding from the intake conversation + repo.

    The understanding comes from what the stakeholder and Quincy worked out
    together during intake, and is stored as the ``brief`` (the decomposition
    input + merge-report context). ``doctrine``, when supplied, is the trusted
    planning doctrine Quincy should shape the understanding by. ``charter_block``
    is the TRUSTED operator charter rendered by the caller (goal/constraints/
    posture — honored, never second-guessed); ``map_block`` is the UNTRUSTED
    recon map rendered through the hardened ``mapview`` boundary (scoping data,
    never instruction). Both are pre-rendered text so this layer stays decoupled
    from the persistence shapes.
    """
    # Same two-speaker rule as `chat`, and it matters more here: this transcript becomes the
    # DURABLE project brief. The `else` used to attribute every non-user role to Quincy, so an
    # engine `note` row saying a turn failed would be synthesized into the project's own statement
    # of intent as something Quincy said. The caller filters (`conversation_turns`); this is the
    # backstop. Agents never imports memory, hence the literals.
    convo = "\n".join(
        f"{'Stakeholder' if m.get('role') == 'user' else 'Quincy'}: {m.get('content', '')}"
        for m in messages
        if m.get("role") in ("user", "pm") and m.get("content", "").strip()
    )
    doctrine_block = f"## Planning doctrine (follow it)\n{doctrine}\n\n" if doctrine.strip() else ""
    charter_part = f"{charter_block.strip()}\n\n" if charter_block.strip() else ""
    map_part = f"{map_block.strip()}\n\n" if map_block.strip() else ""
    human = (
        f"{doctrine_block}{charter_part}## Repository overview\n{repo_overview}\n\n"
        f"{map_part}## Intake conversation\n{convo or '(no conversation yet)'}"
    )
    system = _augment_system(_UNDERSTANDING_SYSTEM, capabilities, _UNDERSTANDING_CAPABILITY_CLAUSE)
    response = robust_invoke(model, [SystemMessage(content=system), HumanMessage(content=human)])
    return message_text(response).strip() or _FALLBACK_BRIEF


_DECOMPOSE_SYSTEM = (
    PM_CAPABILITIES + "\n\n"
    "You are a technical project manager turning an approved Project Brief into an "
    "implementable backlog. Break the work into a small, ordered set of concrete items "
    "(prefer 3 to 8), each independently implementable and testable. "
    "SIZE EACH ITEM AS ONE MERGE REQUEST: a single coherent change that a reviewer can "
    "read and merge on its own — it builds (its tests pass) and makes sense in isolation. "
    "Do NOT split one change so finely that a piece can't stand alone: an interface and the "
    "code that implements it, or a function and its own tests, are ONE item, not two. "
    "Conversely, don't bundle unrelated changes into one item. When two pieces of work are "
    "so coupled that neither is reviewable without the other, make them a single item. "
    "Order them so an item comes AFTER the items it needs, and wire that ordering explicitly "
    "with dependencies. "
    "Return ONLY a JSON array; each element is an object with keys: "
    '"title" (short imperative), "description" (what to do, grounded in the repo), '
    '"acceptance" (how we know it is done — a STRING with one criterion per line, or a JSON '
    "array of criterion strings; never one run-on line bundling several criteria), and "
    'optionally "depends_on" (a list of the '
    "1-based positions in THIS array of the earlier items this one depends on — reference "
    "only items that appear before it; omit or use [] when it has no prerequisites). "
    "ACCEPTANCE STATES OBSERVABLE BEHAVIOUR: never invent exact reason strings, literal "
    "return tuples, or exact output formats the stakeholder didn't specify (they become an "
    "immovable test contract); for a non-refactor item avoid behaviour-preservation phrasing "
    "like 'same output as <another input/command>' (say 'matches the output of X'); and do "
    "not add an item whose acceptance another item already covers. "
    "EVERY ITEM MUST HAVE OBSERVABLE BEHAVIOUR a test can assert (given inputs, visible "
    "outputs or effects) — never emit scaffolding-only items (package markers, empty "
    "configs, entry-point stubs) whose acceptance is mere existence or importability; fold "
    "scaffolding into the first item that uses it. "
    "No prose outside the JSON."
)


def _extract_json_array(text: str) -> Any:
    """Parse a JSON array from model output, tolerating code fences / surrounding prose.

    For ``decompose_brief`` and ``curate_backlog`` ONLY. Both are told to emit nothing but the
    array (``_DECOMPOSE_SYSTEM``: "No prose outside the JSON"; ``_CURATE_SYSTEM``: "Output ONLY
    the JSON array"), so the unfenced fallback below is the correct reading of their contract —
    a fence is the deviation there, not the rule.

    The chat path deliberately does NOT use this: its prompt asks for a fenced block and
    ``_fenced_changeset`` holds it to that. Do not "unify" the two — the looseness here is a
    feature of a prompt that forbids prose, and a bug in one that invites it."""
    fenced = _JSON_BLOCK.search(text)
    candidate = fenced.group(1) if fenced else text
    if not fenced:
        start, end = candidate.find("["), candidate.rfind("]")
        if start != -1 and end > start:
            candidate = candidate[start : end + 1]
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        return None


def decompose_brief(
    model: BaseChatModel,
    brief: str,
    repo_overview: str,
    capabilities: str = "",
    doctrine: str = "",
    code_evidence: str = "",
) -> list[dict[str, Any]]:
    """Decompose an approved brief into an ordered, dependency-wired backlog.

    Returns a list of ``{title, description, acceptance, depends_on}`` where
    ``depends_on`` is a list of 1-based positions in the RETURNED list (each
    strictly less than the item's own position, so the graph is acyclic by
    construction). ``doctrine``, when supplied, is the trusted planning doctrine
    Quincy decomposes by. Falls back to a single item covering the whole brief
    when the model output can't be parsed.
    """
    doctrine_block = f"## Planning doctrine (follow it)\n{doctrine}\n\n" if doctrine.strip() else ""
    human = f"{doctrine_block}## Approved brief\n{brief}\n\n## Repository overview\n{repo_overview}"
    # Decompose sees the file LISTING; `code_evidence` is the contents of the files the brief
    # actually names, so the criteria it authors describe real behaviour (F60, #70). Empty for a
    # caller with no clone, which keeps every existing prompt byte-identical.
    if code_evidence.strip():
        human = f"{human}\n\n{code_evidence}"
    system = _augment_system(_DECOMPOSE_SYSTEM, capabilities, _DECOMPOSE_CAPABILITY_CLAUSE)
    response = robust_invoke(model, [SystemMessage(content=system), HumanMessage(content=human)])
    parsed = _extract_json_array(message_text(response))
    # First pass: keep titled entries, remembering each one's ORIGINAL 1-based index
    # in the model's array so depends_on references (which point at that array) can be
    # remapped onto the filtered output positions below.
    entries: list[tuple[int, dict[str, Any]]] = []
    if isinstance(parsed, list):
        for i, entry in enumerate(parsed):
            if isinstance(entry, dict) and str(entry.get("title", "")).strip():
                entries.append((i + 1, entry))
    pos_of = {orig: out for out, (orig, _e) in enumerate(entries, start=1)}
    items: list[dict[str, Any]] = []
    for out_pos, (_orig, entry) in enumerate(entries, start=1):
        deps: list[int] = []
        for d in entry.get("depends_on") or []:
            # Accept only backward references to real items → no cycles, no forward/self refs.
            if isinstance(d, int) and d in pos_of and pos_of[d] < out_pos and pos_of[d] not in deps:
                deps.append(pos_of[d])
        items.append(
            {
                "title": str(entry["title"]).strip()[:512],
                "description": str(entry.get("description", "")).strip(),
                "acceptance": acceptance_text(entry.get("acceptance")),
                "depends_on": deps,
            }
        )
    if not items:
        items = [
            {
                "title": "Implement the brief",
                "description": brief,
                "acceptance": "",
                "depends_on": [],
            }
        ]
    return items


# The shared backlog-changeset op grammar — used by BOTH the curator and the PM chat so
# Quincy proposes the SAME approvable ops wherever the stakeholder talks to him.

_CURATE_SYSTEM = (
    PM_CAPABILITIES + "\n\n"
    "You are Quincy, the PM, curating an EXISTING project backlog you own. You are given the "
    "brief and the current backlog (each item with its id, status, position, dependencies, and "
    "lock), plus optionally an instruction. Propose a CHANGESET: a JSON array of operations. "
    "NOTHING is applied until the human approves — you are proposing, not doing.\n"
    + _CHANGESET_OPS
    + "Follow the planning doctrine. Sequence by dependency; when an item should wait for items "
    "it depends on, set_dependencies AND soft-lock it with a caveat. Split an item that bundles "
    "multiple concerns into focused children; MERGE or DEDUPLICATE near-duplicate items (same or "
    "overlapping title/description/acceptance) by folding them into one via merge; delete an item "
    "that is obsolete or superseded. Each item ships as ONE merge request, so keep items "
    "MR-sized: MERGE items so tightly coupled that neither is reviewable or mergeable without the "
    "other (e.g. an interface and its implementation) into one. Propose only changes that "
    "genuinely improve the backlog; return an empty array [] if nothing should change. Output "
    "ONLY the JSON array."
)


def curate_backlog(
    model: BaseChatModel,
    backlog: str,
    brief: str,
    instruction: str = "",
    doctrine: str = "",
    capabilities: str = "",
    code_evidence: str = "",
) -> list[dict[str, Any]]:
    """Propose a backlog changeset (reorder / enhance / lock / unlock / set_dependencies)
    over the EXISTING items — a review-only proposal, applied only after human approval.
    Returns the parsed op dicts (empty when the output can't be parsed — nothing to
    propose).

    ``code_evidence`` is the quoted contents of repo files the backlog names, built by
    ``mosaera_core.grounding_text.ground_named_files``. Curate is the stage that WRITES the
    acceptance bar and it has never been able to read the repository (F60, #70) — hence a
    specified `budget status` output format that did not exist. Defaults empty, so a caller
    without a clone (the QMB harness, the offline tests) sends the prompt it always sent.
    """
    sections: list[str] = []
    if doctrine.strip():
        sections.append(doctrine)
    sections += [f"## Project brief\n{brief}", f"## Current backlog\n{backlog}"]
    if code_evidence.strip():
        sections.append(code_evidence)
    if instruction.strip():
        sections.append(f"## Instruction\n{instruction}")
    response = robust_invoke(
        model,
        [
            # Curate was the ONE backlog prompt with no capability ceiling: it bypassed
            # `_augment_system` entirely while chat and decompose both got one — and it is the
            # operation that `add`s and `split`s, i.e. the one most able to mint unbuildable work.
            # It also runs automatically on every fresh backlog and from the escalation path.
            SystemMessage(
                content=_augment_system(_CURATE_SYSTEM, capabilities, _CURATE_CAPABILITY_CLAUSE)
            ),
            HumanMessage(content="\n\n".join(sections)),
        ],
    )
    parsed = _extract_json_array(message_text(response))
    if not isinstance(parsed, list):
        return []
    return [op for op in parsed if isinstance(op, dict) and str(op.get("op", "")).strip()]


# NOTE: the display name must match PM_NAME in apps/web/src/components/pm/PmMessage.tsx.


def chat_system_prompt(capabilities: str = "") -> str:
    """Quincy's conversational system prompt, exactly as `chat` builds it.

    Public so the tool-using path can hand the SAME string to `build_pm_agent`, where the system
    prompt is a constructor argument rather than the first message. Both paths must produce the
    identical prompt: it is what makes turning the ledger tools on a clean comparison instead of
    two changes at once. Nothing here mentions the tool — the model learns about it through the
    tool-calling API, so the prompt is one less thing that differs between the arms.
    """
    return _augment_system(_CHAT_SYSTEM, capabilities, _CHAT_CAPABILITY_CLAUSE)


def chat(
    model: BaseChatModel,
    context: str,
    history: Sequence[dict[str, str]],
    user_message: str,
    capabilities: str = "",
) -> tuple[str, list[dict[str, Any]], dict[str, str] | None, dict[str, Any] | None]:
    """Continue a PM conversation. Returns ``(reply, changeset, charter_proposal,
    clarification)``: the reply has any trailing fenced blocks stripped for display;
    ``changeset`` is the list of proposed backlog ops; ``charter_proposal`` is a proposed
    ``{goal, constraints, posture}`` (or None); ``clarification`` is a proposed intake
    question ``{item_id, claim_text, why, proposals}`` (or None). ALL are PROPOSALS —
    applied only after the stakeholder approves in the UI (ADR-0080: the model may propose,
    the operator's acceptance is what mints ENTAILED)."""
    system = chat_system_prompt(capabilities)
    messages: list[Any] = [SystemMessage(content=system), HumanMessage(content=context)]
    # Shared with the tool-using path (`_chat_agent.chat_with_agent`), so the two can never
    # disagree about what the model is shown — including the control that keeps an engine `note`
    # row from replaying as operator speech.
    messages.extend(replay(history))
    messages.append(HumanMessage(content=user_message))

    raw = message_text(robust_invoke(model, messages)).strip()
    # One call, two results: the ops and the text with exactly those ops removed. An unfenced
    # array is not a proposal here and is not stripped either — it stays in `visible`, so a
    # refused proposal is something the operator can SEE rather than something that vanished.
    changeset, visible = _extract_changeset(raw)
    charter = _extract_charter(raw)
    clarification = _extract_clarify(raw)
    reply = _CLARIFY_BLOCK.sub("", _CHARTER_BLOCK.sub("", visible)).strip()
    if not reply:
        # F48: this fallback used to fire unconditionally, collapsing two very different turns.
        # When the model answered with ONLY a fenced block, a preamble is right — the proposal card
        # carries the content. When it produced NOTHING usable, the same sentence made a failed
        # turn look like an answer: no card, no failure indicator, the panel back to "No active
        # work right now". Observed ~5x in one thread, including on a direct actionable question.
        #
        # Deny-by-default applied to conversation: no content, no answer. "" is returned so the
        # caller can surface the failure instead of rendering a sentence that means nothing.
        reply = "Here's what I'd suggest." if (changeset or charter or clarification) else ""
    return reply, changeset, charter, clarification


_SUMMARIZE_SYSTEM = (
    "You summarize project files for a project manager's long-lived context. "
    "Reply with 1-3 plain sentences capturing what the file is and the rules or "
    "facts it establishes. No preamble, no markdown, no bullet points."
)


def summarize_file(model: BaseChatModel, filename: str, text: str) -> str:
    """1-3 sentence summary of an uploaded file (for context injection)."""
    prompt = f"File: {filename}\n\n{text[:12000]}"
    response = robust_invoke(
        model, [SystemMessage(content=_SUMMARIZE_SYSTEM), HumanMessage(content=prompt)]
    )
    return message_text(response).strip()
