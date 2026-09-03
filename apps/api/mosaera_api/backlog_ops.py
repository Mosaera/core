"""Backlog curation and changeset application, extracted from ``projects.py``.

Split out when ``projects.py`` reached the 500-line god-file ceiling — the same remedy
``config/_settings.py`` already applies via ``_from_env``/``_roles``. The division is
cohesive rather than arbitrary: everything here operates on an EXISTING project's backlog,
while what stays behind is about bringing a project into being (intake, the repo overview,
decompose).

``projects.py`` re-exports these names, so ``routes/backlog.py``,
``app_context/_escalation.py`` and ``pmbench_run.py`` are unchanged.
"""

from __future__ import annotations

from typing import Any

from mosaera_agents import pm
from mosaera_core.config import Settings
from mosaera_core.doctrine import load_global_doctrine
from mosaera_core.grounding_text import ground_project_files
from mosaera_core.models import get_chat_model
from mosaera_core.task_spec import acceptance_text
from mosaera_core.tools.repo import (
    describe_coder_capabilities,
)
from mosaera_memory import MemoryStore

from mosaera_api.pm_sections import _render_backlog

# Ops that renumber positions and mint/remove item ids — can't share a changeset with
# reorder/set_dependencies (which reference a now-stale id/position snapshot).
_STRUCTURAL_OPS = frozenset({"split", "merge", "delete"})


def curate_backlog(
    memory: MemoryStore, project_id: str, instruction: str = ""
) -> list[dict[str, Any]]:
    """Ask Quincy to PROPOSE a backlog changeset (review-only — nothing is applied).
    Synchronous, like pm_chat: one model call, returns the proposed ops."""
    settings = Settings.from_env()
    detail = memory.project_detail(project_id)
    if not detail:
        return []
    model = get_chat_model("pm", settings)
    backlog = _render_backlog(memory.list_backlog_items(project_id))
    doctrine = load_global_doctrine() if settings.doctrine_enabled else ""
    # Select on the backlog PLUS the instruction: the operator naming a file ("the acceptance for
    # #12 should match src/cli.py") is as good a pointer as an item that names one.
    code_evidence = ground_project_files(
        settings.projects_dir, project_id, f"{backlog}\n{instruction}"
    )
    return pm.curate_backlog(
        model,
        backlog,
        str(detail.get("brief", "")),
        instruction,
        doctrine,
        code_evidence=code_evidence,
        capabilities=describe_coder_capabilities(
            settings.delete_tool_enabled, settings.coder_repl_enabled
        ),
    )


#: Statuses whose row is the RECORD of work that exists in the repository.
_DELIVERED_STATUSES = frozenset({"done", "in_review"})


def _destroys(op: dict[str, Any]) -> list[int]:
    """The item ids this op DELETES a row for. Empty for a non-destructive op.

    `delete` is the obvious one. `split` deletes the parent it replaces and `merge` deletes every
    source it folds in — both reachable from the same model-proposed changeset, which is why the
    store's sibling MR guard had to cover all three.
    """
    kind = str(op.get("op", ""))
    if kind == "delete":
        return [int(op.get("id", -1))]
    if kind == "split":
        return [int(op.get("id", -1))]
    if kind == "merge":
        return [int(x) for x in op.get("sources", [])]
    return []


def _refuse_destroying_delivered(
    changeset: list[dict[str, Any]], rows: dict[int, dict[str, Any]]
) -> None:
    """Refuse to delete the record of work that was actually delivered.

    `_refuse_if_mr_live` (store) already covers a row whose merge request is OPEN. It does not
    cover the case measured here: an item `done` or `in_review` whose work was committed but which
    has NO merge request — the state the `delivered_no_mr` decision exists to report, and the
    majority state on a project that has been running autonomously.

    Why this is a deterministic guard and not a better prompt. Asked to tidy the backlog, the PM
    proposed deleting twelve items, five of them delivered work with runs and branches behind them.
    Asked in the SAME conversation whether that was safe, it said no and explained precisely what
    would be lost. The knowledge was there; the path that produced the ops did not use it. An
    operator who clicks Apply — the one-click path, and the one a non-technical operator reaches
    for — loses the project's history. A control that depends on which code path the model took is
    not a control (ADR-0063).

    The override is deliberately NOT a field on an op. The threat is a model-authored changeset an
    operator accepts, so a flag the changeset itself could set would be granted by the same text it
    guards. It is a parameter of the human's own call instead — the ADR-0105 rule that authority
    flows from the authenticated request, never from model output.
    """
    blocked: list[str] = []
    for op in changeset:
        for item_id in _destroys(op):
            row = rows.get(item_id)
            if row is None:
                continue
            status = str(row.get("status") or "")
            if status in _DELIVERED_STATUSES or row.get("mr_url") or row.get("branch"):
                blocked.append(f"#{item_id} ({status or 'no status'})")
    if blocked:
        raise ValueError(
            "refusing to delete delivered work: "
            + ", ".join(sorted(set(blocked)))
            + ". These rows are the record of what was built — the branch a merge request "
            "sources from, and the history a run points at. Re-open the item, or confirm "
            "explicitly that you want the record removed."
        )


def apply_backlog_changeset(
    memory: MemoryStore,
    project_id: str,
    changeset: list[dict[str, Any]],
    *,
    allow_delivered: bool = False,
) -> list[dict[str, Any]]:
    """Validate a changeset structurally (reject the WHOLE set on any bad op — deny by
    default), then apply each op via the store primitives. Returns the resulting backlog.
    Raises ValueError on invalid input (→ HTTP 400)."""
    rows = {int(i["id"]): i for i in memory.list_backlog_items(project_id)}
    ids = set(rows)
    if not allow_delivered:
        _refuse_destroying_delivered(changeset, rows)
    kinds = {str(op.get("op", "")) for op in changeset}
    # Structural ops renumber positions and mint/remove ids, so a reorder/set_dependencies
    # op in the same changeset would apply against a stale id/position snapshot.
    if kinds & _STRUCTURAL_OPS and kinds & {"reorder", "set_dependencies"}:
        raise ValueError("a changeset cannot mix split/merge/delete with reorder/set_dependencies")
    touched: set[int] = set()  # items a structural op operates on (must be disjoint)
    for op in changeset:
        kind = str(op.get("op", ""))
        if kind == "reorder":
            if {int(x) for x in op.get("ordered_ids", [])} != ids:
                raise ValueError("reorder must list exactly the current item ids")
        elif kind == "add":
            if not str(op.get("title", "")).strip():
                raise ValueError("add: title is required")
        elif kind in ("enhance", "lock", "unlock", "set_dependencies", "delete"):
            if int(op.get("id", -1)) not in ids:
                raise ValueError(f"{kind}: unknown item {op.get('id')}")
            # The DEPENDS_ON ids were unvalidated while `reorder`'s id list was checked. The store
            # rejects an unknown dependency, but it does so at APPLY time — and each op is its own
            # transaction, so the raise would land after earlier ops had already been written,
            # leaving a partially-applied changeset. This validator exists precisely so a bad op
            # rejects the whole set before anything is written.
            if kind == "set_dependencies":
                unknown = [int(x) for x in op.get("depends_on", []) if int(x) not in ids]
                if unknown:
                    raise ValueError(f"set_dependencies: unknown item(s) {unknown}")
        elif kind == "split":
            if int(op.get("id", -1)) not in ids:
                raise ValueError(f"split: unknown item {op.get('id')}")
            parts = op.get("parts")
            if (
                not isinstance(parts, list)
                or not parts
                or not all(isinstance(p, dict) and str(p.get("title", "")).strip() for p in parts)
            ):
                raise ValueError("split: parts must be a non-empty list of titled objects")
        elif kind == "merge":
            if int(op.get("target", -1)) not in ids:
                raise ValueError(f"merge: unknown target {op.get('target')}")
            sources = [int(x) for x in op.get("sources", [])]
            if not sources or any(x not in ids for x in sources):
                raise ValueError("merge: sources must be non-empty existing items")
            if int(op["target"]) in sources:
                raise ValueError("merge: target cannot be one of its own sources")
        else:
            raise ValueError(f"unknown op: {kind!r}")
        for part in (op, *(op.get("parts") or [] if kind == "split" else [])):
            if not isinstance(part.get("acceptance") or "", (str, list)):
                raise ValueError(f"{kind}: acceptance must be a string or a list of strings")
        # Two structural ops touching the same item would leave a stale reference mid-apply.
        if kind in _STRUCTURAL_OPS:
            here = (
                {int(op["target"]), *[int(x) for x in op.get("sources", [])]}
                if kind == "merge"
                else {int(op["id"])}
            )
            if touched & here:
                raise ValueError("two structural ops touch the same item")
            touched |= here
    for op in changeset:
        kind = op["op"]
        if kind == "add":
            continue  # applied last so reorder/structural ops keep their id/position snapshot
        if kind == "reorder":
            memory.reorder_backlog(project_id, [int(x) for x in op["ordered_ids"]])
        elif kind == "enhance":
            memory.update_backlog_item(
                int(op["id"]),
                title=op.get("title"),
                description=op.get("description"),
                acceptance=acceptance_text(op["acceptance"]) if op.get("acceptance") else None,
            )
        elif kind == "lock":
            memory.set_item_lock(int(op["id"]), True, str(op.get("reason", "")))
        elif kind == "unlock":
            memory.set_item_lock(int(op["id"]), False)
        elif kind == "set_dependencies":
            memory.set_item_dependencies(int(op["id"]), [int(x) for x in op.get("depends_on", [])])
        elif kind == "split":
            parts = [{**p, "acceptance": acceptance_text(p.get("acceptance"))} for p in op["parts"]]
            memory.split_backlog_item(int(op["id"]), parts)
        elif kind == "merge":
            memory.merge_backlog_items(
                int(op["target"]),
                [int(x) for x in op["sources"]],
                title=op.get("title"),
                description=op.get("description"),
                acceptance=acceptance_text(op["acceptance"]) if op.get("acceptance") else None,
            )
        elif kind == "delete":
            memory.delete_backlog_item(int(op["id"]))
    # New items append after everything else, so any reorder/structural op above kept
    # operating on the id/position snapshot it was validated against.
    adds = [op for op in changeset if op.get("op") == "add"]
    if adds:
        start = max((i["position"] for i in memory.list_backlog_items(project_id)), default=-1) + 1
        for offset, op in enumerate(adds):
            memory.add_backlog_item(
                project_id,
                str(op["title"]).strip()[:512],
                str(op.get("description", "")).strip(),
                acceptance_text(op.get("acceptance")),
                start + offset,
            )
    return memory.list_backlog_items(project_id)


# ADR-0105: how Quincy refers to a decision the SERVER already owns. Deliberately a marker and
# not a fenced block — it appears mid-sentence, and the id is validated against the live set.
