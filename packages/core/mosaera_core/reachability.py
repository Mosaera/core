"""Is this item BUILDABLE by the engine's toolset? — the third intake axis (F76, #78).

`spec_lint` asks whether an acceptance criterion can be CHECKED and whether it DECIDES one answer.
Neither asks whether the work it demands is something this engine can perform, and an item can pass
both while being impossible. Item 88 was exactly that: *"No file under src/budget_tracker.egg-info/
remains tracked in the repository"* — checkable, decidable, and requiring a git operation no tool
performs. Five runs, ~2.9M tokens, and it then presented at the escalation gate as a TEST problem,
where the natural repair (amend the blocking test) would have laundered a capability gap into a
green run.

Its own module rather than a fourth section of `spec_lint` because it asks a different question:
the others read the SPEC, this one compares the spec against the ENGINE. It is also the only intake
check that reads `mosaera_policies` — the capability inventory is the trust boundary's own
statement about what the delivery agent can do, and this module is the one place that statement
meets an acceptance criterion.

Same contract as its siblings: pure, deterministic, no I/O, no model, todo-only, derived at read
and never stored.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.spec_lint import SpecFinding


def unreachable_reason(claim_text: str) -> str:
    """WHY this claim demands work the engine cannot perform, or ``""``. Deterministic (F76, #78).

    See the module docstring for what this axis is for and what it cost to learn.

    **ONE rule over data, on purpose.** It matches against `OUT_OF_CAPABILITY`, which is the same
    list the PM prompt renders from, so a capability added there reaches both and neither can drift.
    A regex per defect is what ADR-0085 calls *"a photograph of a defect we already saw"* — the next
    unreachable class is closed by naming a capability, not by growing this function.

    **Precision over recall**, matching this module's stated bar. It fires on a claim that ASKS for
    an action, not on one that merely mentions the noun: "the README documents the git workflow" is
    reachable. So a phrase must appear as a demand — hence the imperative-ish surface forms in
    `asks_for` rather than bare keywords.
    """
    from mosaera_policies.allowlist import OUT_OF_CAPABILITY

    text = claim_text.lower()
    for entry in OUT_OF_CAPABILITY:
        # Two parts: an unambiguous demand, OR a weak term in the right company. Item 88's
        # criterion never says "git" — it says "remains TRACKED in the REPOSITORY" — so a keyword
        # list missed it, and bare "git" as a trigger would fire on "documents the git workflow".
        hit = any(phrase in text for phrase in entry.asks_for) or (
            any(term in text for term in entry.weak_terms)
            and any(word in text for word in entry.context)
        )
        if hit:
            return f"needs {entry.phrase}, which the delivery agent cannot do ({entry.because})"
    return ""


def reachability(items: list[dict[str, Any]]) -> dict[int, str]:
    """Per-item REACHABLE / UNREACHABLE — can the engine's toolset actually do this work?

    Same contract as its two siblings: todo-only, pure, deterministic, no I/O. Derived at read and
    never stored, so the verdict stays honest as the capability inventory changes rather than
    freezing today's toolset into a column.
    """
    from mosaera_core.claims import claims_from_acceptance

    verdicts: dict[int, str] = {}
    for item in items:
        if str(item.get("status", "todo")) != "todo":
            continue
        item_id = int(item["id"])
        claims = claims_from_acceptance(item_id, str(item.get("acceptance") or ""))
        blocked = [c for c in claims if c.material and unreachable_reason(c.text)]
        verdicts[item_id] = "UNREACHABLE" if blocked else "REACHABLE"
    return verdicts


def reachability_findings(
    items: list[dict[str, Any]],
    *,
    include_description: bool = False,
    statuses: frozenset[str] | None = None,
) -> list[SpecFinding]:
    """UNREACHABLE claims as findings for the same one-pass re-curate loop as its siblings.

    Report-only until `intake_ask_unreachable` is on — the ask-rate is a measured dial, and a false
    ask blocks legitimate work behind a question (ADR-0080's clarification-fatigue hazard).

    The two parameters both default to today's behaviour, and exist so the ASK path and the REPORT
    path can differ without a second copy of the rule — the drift ADR-0089 was written about.

    The ask path stays narrow because an ask is an interruption: only a `todo` item, only its
    acceptance criteria, because that is what a clarification can actually amend. A report is not
    an interruption, so it may look wider — at an item already `deferred` or `in_progress`, and at
    the description, which is where an item that never received acceptance criteria states what it
    wants. On the LedgerCLI backlog, the items demanding a git operation carried empty acceptance
    and non-`todo` statuses, so the narrow reading saw nothing at all while a whole run was spent
    discovering it.
    """
    from mosaera_core.claims import claims_from_acceptance

    findings: list[SpecFinding] = []
    allowed = statuses if statuses is not None else frozenset({"todo"})
    for item in items:
        if str(item.get("status", "todo")) not in allowed:
            continue
        item_id = int(item["id"])
        text = str(item.get("acceptance") or "")
        if include_description:
            text = f"{text}\n{item.get('description') or ''}".strip()
        for claim in claims_from_acceptance(item_id, text):
            reason = unreachable_reason(claim.text) if claim.material else ""
            if reason:
                findings.append(
                    SpecFinding(
                        item_id,
                        "unreachable_claim",
                        f'item #{item_id}: "{claim.text[:90]}" {reason}. Re-scope this criterion '
                        "to what the delivery agent can build, and record the rest as a manual "
                        "step — an item that cannot be built burns a whole run before saying so.",
                    )
                )
    return findings
