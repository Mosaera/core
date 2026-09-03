"""Renderers for each project-state section of the PM prompt.

One function per section — backlog item, run, charter. Extracted from `pm_context_builder` when
the run renderer grew: the builder assembles and budgets, these decide how one row READS. Keeping
them apart matters because the reading is where the honesty lives — a row that omits what it does
not know reads as though nothing was wrong (F47).
"""

from __future__ import annotations

from typing import Any

from mosaera_core.recon.types import quote_repo_text
from mosaera_core.run_diagnosis import diagnosis_summary

#: How much acceptance text one item may contribute. Ten criteria of ~120 chars is a generous real
#: item; beyond it the remainder is counted rather than quoted, so one sprawling item cannot crowd
#: the rest of the context out (the 2026-08-07 incident: a planner at ten tokens of headroom).
_ACCEPTANCE_CHARS = 1200
#: Statuses whose criteria are still worth reading in full. Delivered work keeps its count only —
#: the bar it was held to is settled, and re-quoting it spends budget on a closed question.
_ACCEPTANCE_LIVE = frozenset({"todo", "in_progress", "deferred", "in_review"})


#: How much acceptance text the WHOLE backlog block may spend, across every item. A per-item cap
#: alone is not enough: 100 items each comfortably inside their own limit still blew a 12,000-token
#: budget to 14,227 in test, which is the 2026-08-07 shape (a planner at ten tokens of headroom,
#: falling back to generic plans). Items are served in order and the rest keep their count.
_ACCEPTANCE_BLOCK_CHARS = 6000
#: Below this the remaining budget cannot fit a useful criterion, so the item renders nothing.
_ACCEPTANCE_MIN_LINE = 40


def _acceptance_detail(
    item: dict[str, Any], criteria: list[str], budget: list[int] | None = None
) -> str:
    """The acceptance TEXT, and what evidence exists for it.

    Quincy was shown `(acceptance: N criteria)` and never the criteria — while the clarify contract
    asks him to judge exactly that text, and the North Star names "does every acceptance criterion
    now have evidence?" as the question he must ask instead of trusting "Done". Both were being
    asked of a surface he could not see. Ten items of acceptance cost ~115 tokens against ~11,400
    unused, so the count was never a budget decision; it was simply never revisited.

    `evidence` arrives pre-reconciled (`mosaera_core.evidence`) because only the caller holds both
    the ledger and the item. UNMEASURED is rendered explicitly: a criterion nobody has evaluated is
    not a failure, and letting it read as one would condemn work nobody has looked at.
    """
    if not criteria or str(item.get("status") or "") not in _ACCEPTANCE_LIVE:
        return ""
    evidence = item.get("evidence") or {}
    verdicts: dict[str, str] = {
        str(c.get("text", "")): str(c.get("verdict", "")) for c in evidence.get("criteria", [])
    }
    # Exhausted means SILENT. A remaining budget too small to fit even one criterion used to emit a
    # "… N more" notice while consuming nothing, so the budget never reached zero and every later
    # item repeated the notice — measured at 77 of them on a 100-item backlog. A cap that turns into
    # a hundred lines of noise is not a cap.
    if budget is not None and budget[0] < _ACCEPTANCE_MIN_LINE:
        return ""
    allowance = min(_ACCEPTANCE_CHARS, budget[0]) if budget is not None else _ACCEPTANCE_CHARS
    lines: list[str] = []
    used = 0
    for raw in criteria:
        text = quote_repo_text(raw, limit=200)
        if used + len(text) > allowance:
            lines.append(f"    … {len(criteria) - len(lines)} more criteria not shown")
            if budget is not None:
                # Spend the block so later items stay silent. This OVERLAPS the min-line guard
                # above — either alone keeps the notice count at one — and the redundancy is kept
                # deliberately: neither is individually load-bearing, and the test asserts the
                # property (at most one notice) rather than the mechanism.
                budget[0] = 0
            break
        mark = ""
        verdict = next((v for t, v in verdicts.items() if t and t in raw), "")
        if verdict:
            mark = f"  [{verdict}]"
        lines.append(f"    · {text}{mark}")
        used += len(text)
    if budget is not None:
        budget[0] -= used
    return "\n" + "\n".join(lines) if lines else ""


def render_backlog_block(rows: list[dict[str, Any]]) -> str:
    """The whole backlog block, sharing ONE acceptance budget across its items.

    The block is rendered here rather than by joining independent lines because the budget is a
    property of the block: a cap each item respects individually still lets a hundred of them
    overflow together, which is exactly what a test measured at 14,227 tokens against 12,000.
    """
    budget = [_ACCEPTANCE_BLOCK_CHARS]
    return "\n".join(_backlog_line(item, budget) for item in rows)


def _backlog_line(item: dict[str, Any], acceptance_budget: list[int] | None = None) -> str:
    """One backlog item for the PM's context: id + status + title, a short description, the
    acceptance criteria themselves, and what evidence exists for each. Rich enough for Quincy to
    discuss items accurately; capped per item so the base block stays bounded."""
    desc = " ".join(str(item.get("description", "")).split())
    if len(desc) > 100:
        desc = desc[:100].rstrip() + "…"
    criteria = [ln for ln in str(item.get("acceptance", "")).splitlines() if ln.strip()]
    # The title is operator/model text spliced into a line-structured block: a newline in it
    # breaks the list and can forge a column-0 `##` heading. `description` was already flattened
    # by the `.split()` above; the title never was.
    title = quote_repo_text(str(item.get("title", "")), limit=200)
    line = f"- #{item.get('id', '?')} [{item.get('status', '?')}] {title}"
    if desc:
        line += f" — {desc}"
    if criteria:
        line += f" (acceptance: {len(criteria)} criteria)"
    # Intake checkability (ADR-0080): Quincy sees WHICH items need clarifying — the clarify
    # fence may only be raised for one of these (pm_chat re-verifies before storing).
    verdict = item.get("checkability")
    if verdict == "UNDER_SPECIFIED":
        line += " [checkability=UNDER_SPECIFIED — needs a clarify proposal]"
    # Decidability is the orthogonal axis: this item's claims BIND to an oracle and still
    # leave their value unstated, so a green run proves nothing about the unstated part.
    # Marked, not fenced. NOTE: `intake_ask` also derives a REACHABILITY axis that is threaded
    # into the turn but has NO marker here, so the server would accept an ask Quincy is never
    # shown — a capability gap, tracked separately, not a rendering bug.
    if item.get("decidability") == "UNDECIDABLE":
        # The marker instructs only when the ask is actually permitted (the knob, and no ratified
        # clause already settling it) — the row carries `ask_axis` from the single askability
        # authority. Without it the line stays advisory, exactly as before.
        tail = (
            " — needs a clarify proposal"
            if item.get("ask_axis") == "decidability"
            else " — a checker binds, but the text doesn't fix the answer"
        )
        line += f" [decidability=UNDECIDABLE{tail}]"
    if isinstance(item.get("clarification"), dict):
        line += " [clarification already OPEN — awaiting the stakeholder]"
    # LAST, because every marker above belongs to the item's ONE summary line and the criteria are
    # indented continuation lines beneath it. Appending them earlier split that line and pushed the
    # markers out of it — caught by the existing decidability test, which reads the `- #id` line.
    return line + _acceptance_detail(item, criteria, acceptance_budget)


def _run_line(run: dict[str, Any]) -> str:
    """One run for the PM's context: what it was, how it ended, and WHY (F47).

    This used to be ``f"- {status} · {task[:60]}"`` — status and a truncated task string, nothing
    else. Asked "why haven't we been able to deliver?", Quincy therefore answered from the
    conversation, and produced a confident four-row diagnosis that was a reformatting of the
    operator's own message from the previous day: two claims about defects that were not present in
    any of the three runs since, none of the three actual terminal causes, and next steps that were
    wasted work.

    The evidence was already here. ``_run_summary`` carries ``diagnosis`` (computed by
    ``runner/_loop.py`` on every live run and persisted), ``termination_reason`` and
    ``validation_status``; the renderer discarded all of it. Same shape as F39 and F41's near-miss —
    evidence in the system that never reaches the surface needing it.

    Absence is stated, never implied: a run with no recorded diagnosis says so, because a missing
    line reads as "nothing went wrong" and that is the failure this exists to stop.
    """
    rid = str(run.get("id", "?"))
    status = str(run.get("status", "?"))
    item = f" item #{run['item_id']}" if run.get("item_id") else ""
    task = " ".join(str(run.get("task", "")).split())[:70]
    line = f"- `{rid}` [{status}]{item} — {task}"

    diagnosis = run.get("diagnosis")
    if isinstance(diagnosis, dict) and diagnosis:
        line += f"\n    {diagnosis_summary(diagnosis)}"
        iteration, cap = diagnosis.get("iteration"), diagnosis.get("max_iterations")
        if iteration and cap:
            line += f" (iteration {iteration}/{cap})"
        # The two facts that most often explain a park, and which the summary line may not name.
        if diagnosis.get("tests_modified"):
            line += "\n    the acceptance tests were modified during this run"
        if diagnosis.get("unsatisfied_claims"):
            claims = ", ".join(str(c) for c in diagnosis["unsatisfied_claims"][:4])
            line += f"\n    unsatisfied acceptance claims: {claims}"
    elif run.get("termination_reason"):
        # Pre-migration-0022 rows carry only the 80-character string.
        line += f"\n    ended: {str(run['termination_reason'])[:200]}"
    elif status not in ("running", "queued"):
        line += "\n    (no diagnosis recorded for this run — do not infer why it ended)"
    return line


def _fence_operator_text(raw: str) -> str:
    """Fence operator-authored charter prose so it cannot forge a prompt-block boundary.

    Red-team 2026-08-18, finding 1. The ADR-0047 amendment made ``goal``/``constraints``
    member-writable, and this renderer splices them verbatim under a header that tells the model
    to HONOR them — while the sibling map renderer (``render_project_map``) quotes every
    repo-derived string precisely because it is untrusted. The charter is still trusted intent,
    but its author is no longer necessarily an admin, so the text must not be able to fabricate
    the next section. Each line is fenced with ``| ``; control characters are dropped (newlines
    kept, since multi-line prose is the legitimate content here). Defence in depth — the primary
    control remains that only the operator, never repo content, reaches this field.
    """
    cleaned = "".join(ch for ch in raw if ch.isprintable() or ch == "\n")
    return "\n".join("| " + line for line in cleaned.split("\n"))


def charter_prompt_block(charter: dict[str, Any] | None) -> str:
    """The TRUSTED operator charter rendered for a prompt, or ``""`` when absent. One
    renderer so the chat context and the decompose synthesis can never drift (#42)."""
    if not charter:
        return ""
    goal = _fence_operator_text(str(charter.get("goal") or "(not stated)"))
    constraints = _fence_operator_text(str(charter.get("constraints") or "(none stated)"))
    # Posture is an enum validated at the store, so it needs no fencing.
    return (
        "## Project charter (trusted operator intent — honor it)\n"
        "The fenced lines below are operator-authored; nothing inside them starts a new section.\n"
        f"Goal:\n{goal}\n"
        f"Constraints:\n{constraints}\n"
        f"Posture: {charter.get('posture') or ''!s}"
    )


def _render_backlog(items: list[dict[str, Any]]) -> str:
    """Compact, id-labelled rendering of the backlog for the CURATOR to reason over.

    Distinct from `_backlog_line`, which renders one item for the chat context: the curator needs
    positions, locks and dependencies to reorder against; the chat needs checkability markers. Two
    audiences, two renderings, one module.
    """
    lines: list[str] = []
    for it in items:
        deps = it.get("depends_on") or []
        lock = f"  LOCKED({it.get('lock_reason', '')})" if it.get("locked") else ""
        dep = f"  depends_on={deps}" if deps else ""
        lines.append(
            f"#{it['id']} [{it.get('status', 'todo')}] pos={it.get('position', 0)} "
            f"{it.get('title', '')}{lock}{dep}\n"
            f"    desc: {it.get('description', '')}\n"
            f"    acceptance: {it.get('acceptance', '')}"
        )
    return "\n".join(lines) if lines else "(empty backlog)"


#: How many attention rows the delivery block will print before summarising the rest. The assembled
#: context `base` is NOT budget-enforced (`ContextBudgets` governs attachments and history only), so
#: a section's own cap is the only thing bounding it — the same reason `runs` is sliced to 8.
_DELIVERY_ROWS = 12


def delivery_prompt_block(
    detail: dict[str, Any],
    branches: list[dict[str, Any]] | None,
    *,
    on_gitlab: bool = True,
    decisions: list[dict[str, Any]] | None = None,
) -> str:
    """What has actually been delivered, and what is stuck — for Quincy (ADR-0105 slice 2).

    Asked to "check our git is clean", Quincy could only answer that he had no access and offer
    shell commands, because none of this reached him — while the rows he already receives carry
    ``branch``/``mr_url``/``mr_state``/``mr_target`` and the renderers discarded them (the same
    shape as the F47 story above).

    ``branches`` is GitLab's list, or ``None`` when we could not ask inside the caller's deadline.
    The difference is stated out loud rather than implied: without it the block says branch state
    was NOT CHECKED, because a model told nothing about branches will otherwise cheerfully report
    that there are no stale ones. Branch names are remote content and go through
    ``quote_repo_text`` — flattened, non-printables stripped, bounded — so a crafted branch name
    cannot fabricate a section header.
    """
    items = list(detail.get("backlog") or [])
    merged = sum(1 for i in items if str(i.get("mr_state") or "") == "merged")
    opened = sum(1 for i in items if str(i.get("mr_state") or "") == "opened")
    closed = sum(1 for i in items if str(i.get("mr_state") or "") == "closed")
    # NOT re-derived. This predicate used to be written out character-identically here and in
    # `decisions._delivered_without_mr` — two origins for one fact, free to drift apart, and the
    # cause of the same items being enumerated in two adjacent sections. The decision owns "what
    # needs action"; this block owns "what is the state" and reads the count off the decision.
    stranded_ids = [
        int(i)
        for d in (decisions or [])
        if d.get("kind") == "delivered_no_mr"
        for i in (d.get("item_ids") or [])
    ]
    project_mr = (
        f"open ({detail.get('status')})" if str(detail.get("mr_url") or "") else "none opened"
    )

    lines = [
        "## Delivery",
        "Recorded delivery state for this project. Item MR states are LAST POLLED and can be "
        "stale; say so rather than asserting they are current.",
        f"- Project merge request: {project_mr}",
        f"- Item merge requests: {merged} merged · {opened} open · {closed} closed",
        f"- Delivered with NO merge request: {len(stranded_ids)}",
    ]

    if branches is None:
        # Two different unknowns, and telling an operator to install a token for a project that
        # has no remote at all is worse than saying nothing (red team 2026-08-19, finding 1).
        why = (
            "no api-scoped token, or GitLab did not answer in time"
            if on_gitlab
            else "this project's source is not on the configured GitLab, so there are no remote "
            "branches to inspect"
        )
        lines.append(
            f"- Branches: NOT CHECKED ({why}). "
            "You do not know whether any branch is stale — say that, do not infer it."
        )
    else:
        live_targets = {
            str(i.get("mr_target") or "") for i in items if str(i.get("mr_state") or "") == "opened"
        }
        live_sources = {
            str(i.get("branch") or "") for i in items if str(i.get("mr_state") or "") == "opened"
        }
        live_sources.add(str(detail.get("mr_source") or ""))
        names = [quote_repo_text(str(b.get("name") or ""), limit=120) for b in branches]
        merged_names = [
            quote_repo_text(str(b.get("name") or ""), limit=120)
            for b in branches
            if b.get("merged") and str(b.get("name") or "") not in live_targets | live_sources
        ]
        lines.append(f"- Branches on the remote ({len(names)}): {', '.join(names) or '(none)'}")
        lines.append(
            "- Merged and no longer needed by an open merge request: "
            f"{', '.join(merged_names) or '(none)'}"
        )

    if stranded_ids:
        # The ids live with the DECISION, next to the id Quincy is meant to cite — enumerating
        # them again here is what made this block the richer, later, competing answer to the same
        # question.
        lines.append("  (these are the `delivered-no-mr` pending decision — see that entry)")
    return "\n".join(lines)


def _overview_caveat(is_current: bool) -> str:
    """The heading suffix that admits the file listing may be out of date.

    Empty in the normal case — the overview is rebuilt whenever the project clone's HEAD has
    moved (0030), so it IS the current tree and saying otherwise would be its own dishonesty.
    Non-empty only when the clone could not be read, which is a different thing from "the repo
    is unchanged" and must not be allowed to read as it. The delivery block draws the same
    distinction with NOT CHECKED, and for the same reason: a model told nothing infers a clean
    answer.
    """
    if is_current:
        return ""
    return (
        " (POSSIBLY STALE — the project clone could not be read this turn, so this is the"
        " last listing we had; do not treat it as the repository's current state)"
    )


#: A ratified decision is short; this bounds a project that has accumulated many.
_CLAUSE_CHARS = 1500


def clauses_prompt_block(clauses: tuple[Any, ...]) -> str:
    """The project's ratified decisions and WHY — the closest thing the codebase has to the
    North Star's *"it works this way because this decision was made"*.

    Clauses were already loaded on every turn and used only to compute which items may be asked
    about; their text never reached the prompt. So Quincy could be told an item needed no
    clarification without ever being told what had settled it, and could not cite the decision when
    asked why a standard is set where it is.

    `because` is operator-authored prose that the system explicitly never parses (`clauses.py:76`),
    which is exactly what makes it safe to render as prose here — nothing downstream reads meaning
    out of it. It is TRUSTED text (a human ratified it), so it takes the charter's `| ` fence rather
    than repo quoting: the fence stops a line starting a section, without implying the content is
    untrusted.
    """
    if not clauses:
        return ""
    lines: list[str] = []
    used = 0
    for clause in clauses:
        value = getattr(clause, "value_num", None)
        setting = f"{clause.binds} = {value}" if value is not None else str(clause.binds)
        because = str(getattr(clause, "because", "") or "").strip()
        entry = f"- {setting} (from {clause.standard_id})" + (f" — {because}" if because else "")
        if used + len(entry) > _CLAUSE_CHARS:
            lines.append(f"- … {len(clauses) - len(lines)} more ratified decisions not shown")
            break
        lines.append(entry)
        used += len(entry)
    body = _fence_operator_text("\n".join(lines))
    return (
        "## Ratified decisions (trusted — the stakeholder settled these)\n"
        "Cite these when asked why a standard is set where it is; they are already decided, so do "
        "not re-open one unless the stakeholder asks.\n" + body
    )


def project_memory_block(answers: list[Any], *, max_findings: int = 3) -> str:
    """What this project's own history says, with the run ids behind every number.

    Everything here is COUNTED, never inferred: `mosaera_core.project_memory` runs fixed queries
    over the run, item and dependency ledgers and returns findings that each carry their evidence.
    So this block is trusted in the same sense the charter is — not because a model asserted it,
    but because it is a tally of rows the engine itself wrote. Quincy may quote the numbers and the
    ids; there is nothing here for a repository to have influenced.

    The ids are the point. "Under-specified acceptance cost 8 runs" invites a follow-up question,
    and the operator can check it — which is the whole difference between this and a model that
    has formed an opinion about the project.

    An answer with no findings still renders its `note`: "no dependency edges are recorded" and
    "nothing is blocked" are the same empty list and opposite facts, and Quincy planning against
    the wrong one is exactly the failure this block exists to prevent.
    """
    sections: list[str] = []
    for answer in answers:
        findings = getattr(answer, "findings", ())
        note = str(getattr(answer, "note", "") or "").strip()
        if not findings and not note:
            continue
        title = str(getattr(answer, "query", "")).replace("_", " ")
        lines = [f"### {title}"]
        if note and not findings:
            lines.append(f"- {note}")
        for finding in findings[:max_findings]:
            runs = getattr(finding, "evidence_runs", ())
            # Two ids, not the whole list: enough to check the claim, cheap enough that every
            # question still fits. The count says how many there are.
            cite = f" [runs: {', '.join(runs[:2])}{'…' if len(runs) > 2 else ''}]" if runs else ""
            lines.append(f"- {finding.summary}{cite}")
        # Name the SHAPE of what is hidden, not just that something is. "(+18 more)" tells a
        # reader something exists and nothing about it; "showing 3 of 21, ranked" tells them this
        # is a head, how long the tail is, and that the tail is smaller — which is what stops
        # "I don't see it" turning into "it isn't there".
        if len(findings) > max_findings:
            lines.append(
                f"- (showing the top {max_findings} of {len(findings)}; the rest are recorded "
                f"but not shown here)"
            )
        sections.append("\n".join(lines))
    if not sections:
        return ""
    return (
        "## What this project's history shows\n"
        "Counted from this project's own run and backlog records — not inference, and not "
        "something you remember. The ids are real; cite them when they matter.\n"
        "This is a SUMMARY, not the whole record: each list is the ranked head of a longer one. "
        "Absence from this block means NOT SHOWN, never NOT RECORDED — if a question needs "
        "something that is not here, look it up if you can, and otherwise say the record has more "
        "than this block carries. Never conclude from this block that something does not exist, "
        "and never answer such a question with a number you did not read or look up.\n\n"
        + "\n\n".join(sections)
    )
