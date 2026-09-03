"""Delivery node: commit on approval and write/persist the run report."""

from __future__ import annotations

from typing import Any

from mosaera_core.graph._baseline import delivery_check, stale_tree_reason
from mosaera_core.graph.context import RunContext
from mosaera_core.graph.state import RunState
from mosaera_core.persist import persist_run
from mosaera_core.report import write_report


def deliver_node(ctx: RunContext, state: RunState) -> dict[str, Any]:
    commit_sha = ""
    refused: dict[str, Any] = {}
    if state.get("approved") and state.get("diff"):
        # The tree that ships must be the tree that passed. `tests_passed` describes the tree the
        # `test` node measured, and two paths change it afterwards — hygiene's autofix writes and
        # routes on without re-testing, and the give-up diversion reaches the gate carrying a
        # verdict from before the coder's last writes. Free when the tree is unchanged.
        check = delivery_check(ctx, state)
        if check.get("verdict") == "failed":
            # Quarantine, never discard: the work survives on its own branch while the item branch
            # — the tip every later item is cut from — stays green. Uncommitted work would be swept
            # by the next run's `reset --hard`, so refusing to commit at all would destroy it.
            quarantine = f"mosaera/quarantine-{ctx.run_id}"
            ctx.workspace.commit_onto(
                quarantine,
                f"mosaera QUARANTINE: {state['task']}\n\nRun: {ctx.run_id}\n"
                f"Failed its own suite after validation; not delivered.",
            )
            refused = {
                "approved": False,
                "quarantine_branch": quarantine,
                "delivery_refused": stale_tree_reason(check, quarantine),
            }
        else:
            commit_sha = ctx.workspace.commit_all(
                f"mosaera: {state['task']}\n\nRun: {ctx.run_id}\nApproved at the human gate."
            )
    report_path = write_report(
        ctx.settings.reports_dir,
        ctx.run_id,
        source=ctx.source,
        branch=ctx.workspace.branch,
        workspace_root=ctx.workspace.root,
        state={**state, **refused},
        commit_sha=commit_sha,
    )
    if ctx.memory is not None:
        # The refusal rides into persist_run, so the durable record says NOT APPROVED with
        # validation_status="failed" rather than quietly recording a delivery that did not happen.
        final_state = {**state, **refused, "report_path": str(report_path)}
        persist_run(
            ctx.memory,
            ctx.settings,
            ctx.run_id,
            source=ctx.source,
            branch=ctx.workspace.branch,
            state=final_state,
            commit_sha=commit_sha,
            project_id=ctx.project_id,
            item_id=ctx.item_id,
            workspace_root=ctx.workspace.root,
        )
    return {"report_path": str(report_path), "commit_sha": commit_sha, **refused}
