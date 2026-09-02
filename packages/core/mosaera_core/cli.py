"""Mosaera CLI: run a governed PM -> Coder -> Reviewer loop over a cloned repo."""

from __future__ import annotations

import argparse
import dataclasses
import shlex
import time
import uuid
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from mosaera_connectors import assemble_pull_request, open_pull_request
from mosaera_memory import MemoryStore

from mosaera_core import __maturity__, __version__
from mosaera_core.config import Settings, load_env
from mosaera_core.graph import build_graph, recursion_limit_for
from mosaera_core.preflight import run_preflight
from mosaera_core.sandbox import SandboxUnavailable, SandboxWorker, create_sandbox
from mosaera_core.tools.repo import clone_repo
from mosaera_core.tools.scan import build_scanners

_PROGRESS_LABELS = {
    "plan": "PM plan ready",
    "implement": "Coder finished",
    "capture": None,
    "test": "Tests executed",
    "scan": "Security scan complete",
    "review": "Review ready",
    "gate": "Gate decision recorded",
    "deliver": "Delivery complete",
}


def _print_update(node: str, update: Any) -> None:
    label = _PROGRESS_LABELS.get(node, node)
    if label is None:
        return
    print(f"\n=== [{node}] {label} ===")
    if not isinstance(update, dict):
        return
    if node == "plan":
        print(update.get("plan", ""))
    elif node == "capture" or node == "implement":
        pass
    elif node == "test":
        print(update.get("test_output", "")[:1500])
    elif node == "scan":
        print(update.get("findings_text", ""))
    elif node == "review":
        print(update.get("review", ""))
    elif node == "deliver":
        print(f"report: {update.get('report_path', '')}")
        if update.get("commit_sha"):
            print(f"commit: {update['commit_sha']}")


def _prompt_decision(payload: Any, auto_approve: bool) -> Any:
    print("\n" + "=" * 70)
    print("HUMAN APPROVAL REQUIRED")
    print("=" * 70)
    if isinstance(payload, dict):
        print(f"action : {payload.get('action', '?')}")
        print(f"summary: {payload.get('summary', '')}")
        for key in (
            "path",
            "content",
            "plan",
            "diff",
            "test_output",
            "findings",
            "review",
            "tests_passed",
            "gate_decision",
        ):
            if key in payload and payload[key] not in ("", None):
                print(f"\n--- {key} ---\n{payload[key]}")
    else:
        print(payload)
    if auto_approve:
        print(">> auto-approved (--approve-all)")
        return {"approve": True}
    answer = input("\nType 'approve' or 'deny <feedback>' > ").strip()
    return answer or "deny (empty answer)"


def _drive(graph: Any, initial: Any, config: dict[str, Any], auto_approve: bool) -> None:
    payload = initial
    while True:
        interrupts: list[Any] = []
        for chunk in graph.stream(payload, config, stream_mode="updates"):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    interrupts.extend(update)
                else:
                    _print_update(node, update)
        if not interrupts:
            return
        resume: dict[str, Any] = {}
        for intr in interrupts:
            resume[intr.id] = _prompt_decision(intr.value, auto_approve)
        payload = Command(resume=resume)


def _cmd_run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if args.ollama_base_url:
        settings = dataclasses.replace(settings, ollama_base_url=args.ollama_base_url)
    if args.sandbox:
        settings = dataclasses.replace(settings, sandbox_backend=args.sandbox)

    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    settings.runs_dir.mkdir(parents=True, exist_ok=True)

    print(f"mosaera run {run_id}")
    print(f"  source repo : {args.repo} (never modified; work happens on a clone)")
    print(f"  task        : {args.task}")
    if args.approve_all:
        print("  WARNING     : --approve-all set; every approval gate auto-approves.")

    workspace = clone_repo(args.repo, settings.workspaces_dir, run_id)
    print(f"  workspace   : {workspace.root} (branch {workspace.branch})")

    try:
        sandbox = create_sandbox(
            settings.sandbox_backend,
            workspace.root,
            image=settings.sandbox_image,
            docker_bin=settings.docker_bin,
            default_timeout=settings.sandbox_timeout,
            install_network=settings.sandbox_install_network,
            index_url=settings.sandbox_index_url,
        )
    except SandboxUnavailable as exc:
        print(f"  ERROR       : {exc}")
        return 2
    backend_note = (
        "hardened container" if settings.sandbox_backend == "docker" else "no-Docker fallback"
    )
    print(f"  sandbox     : {settings.sandbox_backend} ({backend_note})")
    test_cmd = shlex.split(args.test_cmd) if args.test_cmd else None

    # Security scanners run in a separate scan container; Docker-only. When the
    # backend is subprocess (no Docker), scanning is skipped.
    scan_on = settings.scan_enabled and not args.no_scan
    # Fold the --no-scan opt-out into scan_enabled so scan_node's deny-by-default status
    # (ADR-0076) sees it: an explicit opt-out reads as "disabled" (no park), while a missing
    # scan backend under scan_enabled reads as "unavailable" (parks).
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
        print(f"  scanners    : {', '.join(s.name for s in scanners)}")
    elif scan_on:
        # scan_enabled but no Docker backend to run the scan container: security is
        # UNVERIFIED, so the gate will park (ADR-0076). --no-scan opts out cleanly.
        scanners = []
        print("  scanners    : UNVERIFIED (needs Docker; run will park - use --no-scan to skip)")

    # Durable memory + resumable checkpoints when a database is configured;
    # otherwise per-run SQLite checkpoints and no cross-session memory.
    memory: MemoryStore | None = None
    saver: BaseCheckpointSaver
    with ExitStack() as stack:
        if settings.db_url:
            memory = MemoryStore.from_url(settings.db_url)
            memory.init()
            pg = stack.enter_context(PostgresSaver.from_conn_string(settings.db_url))
            pg.setup()  # create checkpoint tables if absent
            saver = pg
            print("  memory      : postgres (durable, resumable)")
        else:
            db_path = settings.runs_dir / f"{run_id}.sqlite"
            saver = stack.enter_context(SqliteSaver.from_conn_string(str(db_path)))
            print("  memory      : sqlite (per-run; set MOSAERA_DB_URL for durable memory)")

        graph = build_graph(
            settings,
            workspace,
            sandbox,
            run_id,
            source=args.repo,
            test_cmd=test_cmd,
            approve_writes=not args.no_write_approval,
            max_iterations=args.max_iterations,
            checkpointer=saver,
            memory=memory,
            scanners=scanners,
            scan_sandbox=scan_sandbox,
        )
        config: dict[str, Any] = {
            "configurable": {"thread_id": run_id},
            "recursion_limit": recursion_limit_for(settings),
        }
        initial = {"task": args.task, "iteration": 0}
        _drive(graph, initial, config, auto_approve=args.approve_all)
        final = graph.get_state(config).values

    print("\n" + "=" * 70)
    print(
        f"run {run_id} finished — status: {'APPROVED' if final.get('approved') else 'NOT APPROVED'}"
    )
    print(f"  report    : {final.get('report_path', '(none)')}")
    print(f"  workspace : {workspace.root}")
    print(f"  branch    : {workspace.branch}")
    print("  the source repository was not modified.")

    if (args.open_pr or args.pr_dry_run) and final.get("approved") and final.get("commit_sha"):
        _maybe_open_pr(args, workspace, run_id, final)

    return 0 if final.get("approved") else 1


def _maybe_open_pr(
    args: argparse.Namespace, workspace: Any, run_id: str, final: dict[str, Any]
) -> None:
    report_text = ""
    report_path = final.get("report_path")
    if report_path:
        try:
            report_text = Path(report_path).read_text(encoding="utf-8")
        except OSError:
            report_text = ""
    plan = assemble_pull_request(
        task=final.get("task", ""),
        run_id=run_id,
        branch=workspace.branch,
        report_text=report_text,
        base=args.pr_base,
    )
    if args.pr_dry_run:
        result = open_pull_request(workspace.root, plan, dry_run=True)
        print("\n  PR (dry run) — commands that would run:")
        for cmd in result.commands:
            print("    " + " ".join(shlex.quote(c) for c in cmd))
        return
    # This interactive confirm IS the authorizing control for the CLI push (ADR-0102 —
    # opening a PR is not graph-gated). --approve-all bypasses it (CI/testing only).
    if not args.approve_all:
        answer = input(f"\nOpen a draft PR for {workspace.branch}? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("  PR not opened.")
            return
    result = open_pull_request(workspace.root, plan)
    if result.opened:
        print(f"  PR opened: {result.url}")
    else:
        print(f"  PR not opened: {result.error}")


# The status glyphs `mosaera doctor` prints. A VM smoke test greps the STATUS WORD, never the
# glyph — a terminal without unicode must not change what a test can assert.
_DOCTOR_GLYPH = {"ok": "\u2713", "note": "\u2013", "fail": "\u2717", "unknown": "?"}


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Report whether this deployment can actually run anything, and name the fix for whatever
    cannot (#119).

    The same checks the first-run wizard renders (`GET /api/preflight`) and the same predicate the
    launch endpoint refuses on — one module, so the CLI and the product cannot tell an operator two
    different stories about one box. Exits NON-ZERO on any failure, which is what makes a
    clean-machine install scriptable: the VM harness runs this, fixes what it names, and runs it
    again.
    """
    settings = Settings.from_env()
    report = run_preflight(settings, verify_keys=not args.offline)
    if args.json:
        import json

        print(json.dumps(report.as_dict(), indent=2))
    else:
        for check in report.checks:
            glyph = _DOCTOR_GLYPH.get(check.status, "?")
            print(f"{glyph} [{check.status:<7}] {check.label}: {check.detail}")
            if check.fix and check.status in ("fail", "note"):
                print(f"      fix: {check.fix}")
        ready, reason = report.can_run()
        print()
        print("READY — this instance can run a task." if ready else f"NOT READY — {reason}")
    # `note` and `unknown` do not fail the command: an in-memory store is a supported state, and a
    # provider we could not reach is not evidence the operator did anything wrong. Only a PROVEN
    # failure is a non-zero exit, so the harness cannot be made red by a flaky network.
    return 1 if any(c.status == "fail" for c in report.checks) else 0


def main(argv: Sequence[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(
        prog="mosaera", description="Mosaera Lite — governed AI software team"
    )
    parser.add_argument(
        "--version", action="version", version=f"mosaera {__version__} ({__maturity__})"
    )  # ADR-0055: engine version; ADR-0088: maturity channel
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run a task against a cloned repository")
    run_p.add_argument("--repo", required=True, help="path or URL of the repository to clone")
    run_p.add_argument("--task", required=True, help="what the team should do")
    run_p.add_argument(
        "--test-cmd", default=None, help="test command (default: python -m pytest -q)"
    )
    run_p.add_argument("--max-iterations", type=int, default=None)
    run_p.add_argument("--no-scan", action="store_true", help="skip security scanners for this run")
    run_p.add_argument(
        "--open-pr",
        action="store_true",
        help="after an approved run, push the branch and open a draft PR (needs gh + a remote)",
    )
    run_p.add_argument(
        "--pr-dry-run",
        action="store_true",
        help="print the git/gh commands the PR flow would run, without executing them",
    )
    run_p.add_argument("--pr-base", default="main", help="base branch for the PR (default: main)")
    run_p.add_argument(
        "--sandbox",
        choices=["docker", "subprocess"],
        default=None,
        help="execution sandbox backend (default: docker; env MOSAERA_SANDBOX)",
    )
    run_p.add_argument(
        "--approve-all", action="store_true", help="auto-approve every gate (CI/testing only)"
    )
    run_p.add_argument(
        "--no-write-approval",
        action="store_true",
        help="gate only delivery, not each individual file write",
    )
    run_p.add_argument("--ollama-base-url", default=None)

    doctor_p = sub.add_parser(
        "doctor", help="check whether this deployment can run anything, and name what is missing"
    )
    doctor_p.add_argument("--json", action="store_true", help="machine-readable output")
    doctor_p.add_argument(
        "--offline",
        action="store_true",
        help="skip provider key verification (no network calls off this box)",
    )

    args = parser.parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "doctor":
        return _cmd_doctor(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
