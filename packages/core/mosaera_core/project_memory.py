"""Project memory — what this project has already learned, read back from its own ledgers.

The engine records a great deal and reads almost none of it back. Every run carries a structured
``diagnosis`` (outcome bucket, park cause, gate reasons); every contract records the item and run
that shipped it. Nothing ever asks "how does this project tend to fail?" or "what already depends
on this?". These are those questions.

**Retrieval, not learning.** Every answer here is a count or a join over recorded facts, and every
finding carries the run and item ids behind it. Nothing is generalised, inferred or remembered:
ask twice, get the same answer, and check it by hand. That is deliberate. A learned lesson steers
future work with no way to audit why, which is the failure mode this system exists to remove; and
a *cited* answer is the stronger product anyway — "runs 41, 47, 52 all ended `under_specified`" is
worth more than "the model thinks this tends to fail".

**Why not let a model write the query.** On BIRD (realistic schemas) the best purpose-built
text-to-SQL systems reach ~82% execution accuracy against a 92.96% human baseline; a plain model
without per-question expert hints is far worse. One answer in five being wrong is disqualifying
when the whole value is citability — a confidently wrong count reads as authoritative. These
queries are fixed and unit-tested instead, so they are right by construction.

Classification reads the STRUCTURED fields (``diagnosis.park_cause``, ``diagnosis.gate_reasons``),
never the prose ``termination_reason``. Those are closed vocabularies the engine already writes;
the prose is kept only as a human-readable exemplar beside the count.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from mosaera_core.recon.types import quote_repo_text

# Terminal buckets, from `mosaera_core.run_diagnosis`. `clean_deliver` is the only success.
FAILED_OUTCOMES: frozenset[str] = frozenset({"honest_park", "thrash_park"})
# Causes that name no mechanism. `classify_park_cause` documents `parked` as the FALLTHROUGH —
# "an autonomous gate park below the cap", i.e. none of the diagnostic branches matched — and an
# empty cause is a run that recorded none at all. Both are common, so ranking purely by count puts
# them on top and buries the causes that actually say something: on a real 92-run project that
# pushed `under_specified` (8 runs, the most actionable pattern there) below a three-line cut,
# behind 19 runs of "we did not record why". They are still reported, as a completeness caveat
# rather than as an insight about how the project fails.
UNDIAGNOSTIC: frozenset[str] = frozenset({"parked", ""})
# Statuses that mean "not finished" — the set the PM reasons about as open work.
_OPEN: frozenset[str] = frozenset({"todo", "in_progress", "in_review", "blocked", "deferred"})


# Item titles and acceptance text are OPERATOR- and MODEL-authored (`op:"add"` / `op:"enhance"`
# both set them), so they are the one untrusted ingredient in an otherwise engine-written record.
# They are quoted HERE, where they enter a finding, rather than at each sink: the standing prompt
# block, the CLI and the read-only history tool all read these fields, and three sinks quoting
# independently is two chances to forget. `quote_repo_text` flattens — which is right for a
# title, and acceptable for acceptance text, which every reader already clips.
#
# Not theoretical: before this, a title containing a newline plus "## What this project's history
# shows" forged that exact heading at column 0 inside the block that rides every PM turn.


@dataclass(frozen=True)
class Finding:
    """One answer, and the evidence for it.

    ``evidence_runs`` / ``evidence_items`` are never empty for a positive finding — a claim
    without ids is exactly the kind of unfalsifiable assertion this module exists to avoid.
    """

    kind: str
    summary: str
    count: int = 0
    evidence_runs: tuple[str, ...] = ()
    evidence_items: tuple[int, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Answer:
    """A query's result. ``findings`` may be empty — ``note`` then says WHY.

    The empty case matters more than it looks: "no items are blocked" and "no dependency edges
    were ever recorded" are the same empty list and opposite facts. Returning a bare nothing for
    the second would be the module quietly lying about the project.
    """

    query: str
    findings: tuple[Finding, ...] = ()
    note: str = ""


def _failed(run: dict[str, Any]) -> bool:
    """A run that did not deliver. Falls back to `status` when `diagnosis` is absent."""
    outcome = (run.get("diagnosis") or {}).get("outcome")
    if outcome:
        return outcome in FAILED_OUTCOMES
    return run.get("status") in {"INCOMPLETE", "ERROR"}


def open_work_and_blockers(items: list[dict[str, Any]]) -> Answer:
    """Open items, and which unfinished items block them — ranked by how much each unblocks.

    This is the "x, y and z are all waiting on AA" question. It is a graph walk, not a judgement:
    a blocker is an item another item declares in ``depends_on`` that is not itself done.
    """
    by_id = {i["item_id"]: i for i in items}
    open_items = [i for i in items if i["status"] in _OPEN]
    if not open_items:
        return Answer("open_work_and_blockers", note="No open items — the backlog is complete.")

    blocks: dict[int, list[int]] = defaultdict(list)
    for item in open_items:
        for dep in item.get("depends_on") or []:
            blocker = by_id.get(dep)
            # An edge to a finished item is satisfied, not blocking. An edge to an item that no
            # longer exists is reported as unknown rather than silently dropped.
            if blocker is None or blocker["status"] in _OPEN:
                blocks[dep].append(item["item_id"])

    if not blocks:
        edges = sum(len(i.get("depends_on") or []) for i in items)
        return Answer(
            "open_work_and_blockers",
            note=(
                f"{len(open_items)} open item(s), none blocked. "
                + (
                    f"The backlog records {edges} dependency edge(s) in total, all satisfied."
                    if edges
                    else "NOTE: this backlog records no dependency edges at all, so 'what blocks "
                    "what' is unanswerable here — the graph is empty, not the answer."
                )
            ),
        )

    findings = []
    for blocker_id, blocked in sorted(blocks.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        blocker = by_id.get(blocker_id)
        raw_title = blocker["title"] if blocker else f"(item {blocker_id} no longer in the backlog)"
        title = quote_repo_text(str(raw_title), limit=200)
        findings.append(
            Finding(
                kind="blocker",
                summary=f"{len(blocked)} open item(s) wait on #{blocker_id} — {title}",
                count=len(blocked),
                evidence_items=(blocker_id, *sorted(blocked)),
                detail={"blocker": blocker_id, "blocks": sorted(blocked)},
            )
        )
    return Answer("open_work_and_blockers", tuple(findings))


def recurring_failures(runs: list[dict[str, Any]]) -> Answer:
    """How this project tends to fail, by structured cause, most common first.

    Counts ``diagnosis.park_cause`` (a closed vocabulary) rather than the prose reason, so the
    grouping cannot drift with wording. The prose is carried through as an exemplar so a reader
    sees a concrete instance beside the number.
    """
    failed = [r for r in runs if _failed(r)]
    if not failed:
        return Answer(
            "recurring_failures",
            note=f"No failed runs among {len(runs)} recorded — nothing to learn from yet.",
        )

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in failed:
        cause = (r.get("diagnosis") or {}).get("park_cause") or ""
        buckets[cause or "(no park cause recorded)"].append(r)

    findings = []
    # Diagnostic causes first, then by count. A reader who sees only the head of this list must
    # see the mechanisms, not the fallthrough.
    ordered = sorted(
        buckets.items(),
        key=lambda kv: (kv[0].strip("()").split()[0] in UNDIAGNOSTIC, -len(kv[1]), kv[0]),
    )
    for cause, rows in ordered:
        exemplar = next((r["termination_reason"] for r in rows if r.get("termination_reason")), "")
        diagnostic = cause not in UNDIAGNOSTIC and not cause.startswith("(no park cause")
        findings.append(
            Finding(
                kind="failure_class",
                summary=(
                    f"{len(rows)} run(s) ended `{cause}`"
                    if diagnostic
                    else f"{len(rows)} run(s) parked with no diagnostic cause recorded (`{cause}`)"
                ),
                count=len(rows),
                evidence_runs=tuple(r["run_id"] for r in rows),
                evidence_items=tuple(sorted({r["item_id"] for r in rows if r.get("item_id")})),
                detail={"park_cause": cause, "example_reason": exemplar, "diagnostic": diagnostic},
            )
        )

    gates: Counter[str] = Counter()
    for r in failed:
        for g in (r.get("diagnosis") or {}).get("gate_reasons") or []:
            gates[g] += 1
    for reason, n in gates.most_common():
        findings.append(
            Finding(
                kind="gate_reason",
                summary=f"the gate refused with `{reason}` {n} time(s)",
                count=n,
                evidence_runs=tuple(
                    r["run_id"]
                    for r in failed
                    if reason in ((r.get("diagnosis") or {}).get("gate_reasons") or [])
                ),
                detail={"gate_reason": reason},
            )
        )
    return Answer("recurring_failures", tuple(findings))


def item_history(
    runs: list[dict[str, Any]], items: list[dict[str, Any]], *, min_runs: int = 3
) -> Answer:
    """Items that took repeated attempts, with how each attempt ended.

    The interesting rows are the ones that fought: an item that landed first time teaches nothing,
    while one that took fifteen runs is where a project's hard-won knowledge actually sits.
    """
    titles = {i["item_id"]: i["title"] for i in items}
    by_item: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        if r.get("item_id") is not None:
            by_item[r["item_id"]].append(r)

    findings = []
    for item_id, rows in sorted(by_item.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(rows) < min_runs:
            continue
        causes = Counter(
            (r.get("diagnosis") or {}).get("park_cause") or "" for r in rows if _failed(r)
        )
        delivered = sum(1 for r in rows if not _failed(r))
        # An item with runs but no title has been deleted or recurated out of the backlog: its
        # history survives and can no longer be explained. Say so rather than printing "?".
        title = quote_repo_text(
            str(titles.get(item_id) or "(no longer in the backlog — history orphaned)"), limit=200
        )
        findings.append(
            Finding(
                kind="contested_item",
                summary=f"#{item_id} took {len(rows)} run(s) ({delivered} delivered) — {title}",
                count=len(rows),
                evidence_runs=tuple(r["run_id"] for r in rows),
                evidence_items=(item_id,),
                detail={"delivered": delivered, "failure_causes": dict(causes)},
            )
        )
    if not findings:
        return Answer("item_history", note=f"No item needed {min_runs}+ runs.")
    return Answer("item_history", tuple(findings))


def criteria_that_failed_here(runs: list[dict[str, Any]], items: list[dict[str, Any]]) -> Answer:
    """Acceptance text of items whose runs died on the acceptance itself.

    Scoped tightly on purpose: only causes that indict the CRITERION (`under_specified`,
    `plan_unworkable`) rather than the implementation. This is the closest this module comes to
    "what not to write again", and it stops at showing the operator the actual text — it does not
    generalise a rule, because a rule nobody ratified is exactly the thing not to build.
    """
    indicting = {"under_specified", "plan_unworkable"}
    acceptance = {i["item_id"]: i.get("acceptance", "") for i in items}
    hits: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        if not _failed(r) or r.get("item_id") is None:
            continue
        if ((r.get("diagnosis") or {}).get("park_cause") or "") in indicting:
            hits[r["item_id"]].append(r)

    if not hits:
        return Answer(
            "criteria_that_failed_here",
            note="No run failed on the acceptance criterion itself.",
        )
    findings = []
    for item_id, rows in sorted(hits.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        text = quote_repo_text(str(acceptance.get(item_id) or ""), limit=2000)
        findings.append(
            Finding(
                kind="weak_criterion",
                summary=f"#{item_id}: {len(rows)} run(s) failed on the criterion, not the code",
                count=len(rows),
                evidence_runs=tuple(r["run_id"] for r in rows),
                evidence_items=(item_id,),
                detail={"acceptance": text or "(no acceptance text recorded)"},
            )
        )
    return Answer("criteria_that_failed_here", tuple(findings))


def orphaned_history(run_item_ids: list[int], items: list[dict[str, Any]]) -> Answer:
    """Runs whose item no longer exists — history the project can no longer explain.

    Not one of the five questions, but the one that decides whether the others can be trusted:
    every orphaned item is a hole in the record, and a memory that cannot say where its holes are
    is worse than one with none.
    """
    live = {i["item_id"] for i in items}
    orphans = sorted(set(run_item_ids) - live)
    if not orphans:
        return Answer("orphaned_history", note="Every run's item is still in the backlog.")
    return Answer(
        "orphaned_history",
        (
            Finding(
                kind="orphaned_items",
                summary=(
                    f"{len(orphans)} item(s) have run history but no longer exist in the backlog — "
                    "their runs cannot be explained"
                ),
                count=len(orphans),
                evidence_items=tuple(orphans),
            ),
        ),
    )
