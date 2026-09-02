"""Default graph factory for the API — wires the real orchestrator like the CLI.

Uses the server-lifetime ``checkpointer`` passed in: a durable PostgresSaver when
MOSAERA_DB_URL is set (so a parked run survives a restart and rehydrates — the cross-restart
resume that was once follow-up work is now live), falling back to an in-process InMemorySaver
when no DB is configured. Durable run memory (MemoryStore) is written whenever a DB is set.
"""

from __future__ import annotations

import dataclasses
import logging
import shlex
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.memory import InMemorySaver
from mosaera_core.clauses import load_clauses
from mosaera_core.config import Settings, apply_oracle_posture
from mosaera_core.graph import build_graph, recursion_limit_for
from mosaera_core.run_context import build_run_context
from mosaera_core.sandbox import SandboxWorker, create_sandbox
from mosaera_core.tools.repo import (
    Workspace,
    check_base_drift,
    clone_repo,
    open_project_workspace,
)
from mosaera_core.tools.scan import build_scanners
from mosaera_memory import MemoryStore

if TYPE_CHECKING:
    from mosaera_api.app import RunSubmit


def _verify_overlay(settings: Settings, req: RunSubmit) -> Settings:
    """Autonomous correctness gate (ADR-0020 + #52/ADR-0057): an autonomous run has no human at the
    delivery gate, so it VERIFIES with the FULL independent oracle — the test-first Proctor authors
    spec-derived asserting acceptance tests, backed by the deterministic supports (change-coverage
    and the mutation check) — and RECOVERS with reason-on-stall, so it can't silently ship wrong
    code. Autonomous-only + opt-out (``autonomous_verified``); ``build_graph`` then splices in the
    author_tests / reason nodes. The exact posture is shared with the benchmark via
    ``apply_oracle_posture`` so the scoreboard and production can't drift. Guided / high-assurance /
    ad-hoc runs are untouched (a human gates delivery)."""
    return apply_oracle_posture(settings) if req.autonomous else settings


def resolve_run_settings(req: RunSubmit, escalation_settings: Settings | None = None) -> Settings:
    """The ``Settings`` a run executes under.

    ``escalation_settings`` (an already-bumped ``Settings`` from ``escalate_role``, for a
    live model-escalation re-run, ADR-0022) short-circuits ``from_env`` + the overlays so the
    re-run uses the escalated bindings verbatim; ``None`` → ``from_env`` + the sandbox /
    cost-mode / verify overlays. Both the factory and ``launch_item`` route through this one
    pure function, so the Settings the graph is built with and the ones the escalation
    diagnoses from are byte-identical — no drift."""
    if escalation_settings is not None:
        return escalation_settings
    settings = Settings.from_env()
    if req.sandbox:
        settings = dataclasses.replace(settings, sandbox_backend=req.sandbox)
    # Cost-mode (#7): overlay the per-run routing tier so build_graph resolves
    # each role's model through it (get_chat_model → role_model). None → default.
    if req.cost_mode:
        settings = dataclasses.replace(settings, active_cost_mode=req.cost_mode)
    return _verify_overlay(settings, req)


def default_graph_factory(
    req: RunSubmit,
    run_id: str,
    checkpointer: Any = None,
    resume: bool = False,
    settings: Settings | None = None,
) -> tuple[Any, dict[str, Any], dict[str, Any] | None, MemoryStore | None]:
    """Build (or REBUILD, when ``resume``) a run's graph.

    ``checkpointer`` is the server-lifetime saver (Postgres) so a parked run's
    state is durable across restarts; falls back to an in-process saver. On
    ``resume`` the workspace is REOPENED without a reset (the coder's uncommitted
    work at the gate must be preserved) and ``initial`` is None so streaming
    replays to the persisted interrupt instead of re-running from the start.

    ``settings`` (a live model-escalation re-run's already-bumped Settings, ADR-0022)
    bypasses ``from_env`` + overlays; ``None`` resolves them normally.
    """
    settings = resolve_run_settings(req, settings)

    # A project item run reuses the project's persistent clone/branch (work
    # accumulates); an ad-hoc run clones the target fresh. On resume, reopen the
    # existing workspace untouched — never reset or re-clone.
    project_context = ""
    if req.project_id:
        # Per-item stacked-MR model (ADR-0021): a fresh item run works on its own
        # branch `mosaera/item-<id>`, cut from the current tip so it still builds on
        # all prior delivered items. On resume, reopen whatever branch is on disk
        # (the coder's uncommitted work lives there) — never re-cut it.
        item_branch = f"mosaera/item-{req.item_id}" if (req.item_id and not resume) else None
        if item_branch:
            # Base-drift check (ADR-0102 slice D), BEFORE the item-branch cut and only on a
            # fresh item run (the project mutex is held; resume never re-cuts). Diverged
            # fails the launch closed — the item stays todo and the caller surfaces the
            # reason (HTTP 400 / project.error) — because a branch cut from a stale tip
            # produces a wrong MR diff. Unreachable proceeds: a correctness aid must not
            # break offline or local-dir use, but the skip is recorded.
            drift = check_base_drift(settings.projects_dir / req.project_id / "repo")
            if drift.kind == "diverged":
                raise RuntimeError(f"base drift: {drift.detail}")
            if drift.kind in ("unreachable", "fast_forwarded"):
                logging.getLogger(__name__).warning(
                    "drift.%s for %s: %s",
                    "check-skipped" if drift.kind == "unreachable" else "fast-forwarded",
                    req.project_id,
                    drift.detail,
                )
        workspace = open_project_workspace(
            settings.projects_dir,
            req.project_id,
            run_id,
            reset=not resume,
            item_branch=item_branch,
        )
        store = MemoryStore.try_open(settings.db_url) if settings.db_url else None
        detail = store.project_detail(req.project_id) if store is not None else None
        brief = str(detail.get("brief", "")) if detail else ""
        # Shared run-time context (#26): brief + backlog + what earlier items built,
        # read back deterministically so this item's run isn't a silo.
        project_context = build_run_context(
            store,
            req.project_id,
            req.item_id,
            brief,
            clauses_enabled=settings.clauses_enabled,
        )
    elif resume:
        # Re-attach to the existing per-run clone (its branch + the coder's
        # uncommitted work are on disk) rather than cloning the source again.
        workspace = Workspace(
            root=(settings.workspaces_dir / run_id).resolve(),
            run_id=run_id,
            branch=f"mosaera/{run_id}",
        )
    else:
        workspace = clone_repo(req.repo, settings.workspaces_dir, run_id)
    sandbox = create_sandbox(
        settings.sandbox_backend,
        workspace.root,
        image=settings.sandbox_image,
        docker_bin=settings.docker_bin,
        default_timeout=settings.sandbox_timeout,
        install_network=settings.sandbox_install_network,
        index_url=settings.sandbox_index_url,
        # For subprocess, install runs on the host — only allow it when install is
        # enabled (config already forces this off unless the opt-in is set).
        allow_install=settings.sandbox_install,
    )

    # Fold the per-request scan opt-out into scan_enabled so scan_node's deny-by-default
    # status (ADR-0076) sees it: opt-out reads as "disabled" (no park); scan_enabled with no
    # Docker scan backend reads as "unavailable" (parks).
    scan_on = settings.scan_enabled and req.scan
    settings = dataclasses.replace(settings, scan_enabled=scan_on)
    scanners = build_scanners() if scan_on else []
    scan_sandbox: SandboxWorker | None = None
    if scanners and settings.sandbox_backend == "docker":
        scan_sandbox = create_sandbox(
            "docker",
            workspace.root,
            image=settings.scan_image,
            docker_bin=settings.docker_bin,
            default_timeout=settings.sandbox_timeout,
        )
    else:
        scanners = []

    # Durable memory is best-effort: a misconfigured/unreachable database must
    # not fail the run (you just lose history). Warn loudly instead.
    memory: MemoryStore | None = None
    if settings.db_url:
        memory = MemoryStore.try_open(settings.db_url)
        if memory is None:
            print(
                f"  WARNING: durable-memory database unreachable at {settings.db_url} — "
                "running without history. Check MOSAERA_DB_URL / MOSAERA_DB_PORT."
            )

    graph = build_graph(
        settings,
        workspace,
        sandbox,
        run_id,
        source=req.repo,
        test_cmd=shlex.split(req.test_cmd) if req.test_cmd else None,
        max_iterations=req.max_iterations,
        checkpointer=checkpointer or InMemorySaver(),
        memory=memory,
        scanners=scanners,
        scan_sandbox=scan_sandbox,
        project_context=project_context,
        item_id=req.item_id,
        project_id=req.project_id,
    )
    config = {
        "configurable": {"thread_id": run_id},
        "recursion_limit": recursion_limit_for(settings),
    }
    # On resume, stream None so LangGraph replays to the persisted interrupt.
    initial = None if resume else {"task": req.task, "iteration": 0}
    # Claim contract (ADR-0079, Wave 1): structured claims ride ALONGSIDE the task string (which
    # stays byte-identical) — read-only in this wave (report rendering); the gate consumes them
    # in a later wave. Empty claims ⇒ current behaviour byte-for-byte.
    if initial is not None and req.claims:
        initial["claims"] = list(req.claims)
    # Standing decisions (ADR-0082 tier 2) ride the same way, resolved ONCE here: the claim
    # oracle is pure and must not reach a database mid-gate. Empty ⇒ byte-identical behaviour,
    # which is also what the default-off knob guarantees.
    if initial is not None and req.project_id:
        clauses = load_clauses(memory, req.project_id, enabled=settings.clauses_enabled)
        if clauses:
            initial["clauses"] = [dataclasses.asdict(c) for c in clauses]
    return graph, config, initial, memory
