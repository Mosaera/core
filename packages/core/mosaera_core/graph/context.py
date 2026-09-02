"""The explicit run context threaded to every node/router/helper, plus the
model/team construction type aliases."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from mosaera_memory import MemoryStore

from mosaera_core.agents_bridge import AgentTeam, ModelFactory
from mosaera_core.config import Settings
from mosaera_core.sandbox import SandboxWorker
from mosaera_core.tools.repo import Workspace
from mosaera_core.tools.scan import Scanner

# The agent-team construction seam, injectable so tests pass a recording/stub factory
# instead of monkeypatching module-global agent builders (default builds the real team).
# It takes ALREADY-BUILT tools (build_graph owns build_repo_tools + protected_tests) plus
# the role→model factory, and returns the AgentTeam the nodes call.
TeamFactory = Callable[[Settings, list, list | None, ModelFactory], AgentTeam]


@dataclass
class RunContext:
    """Explicit context threaded to every module-scope node/router/helper — replaces the
    large set of local closures build_graph used to capture. NOT frozen: it holds the mutable
    `protected_tests` set (the SAME object the coder tools close over AND author_tests_node
    fills) and the run-scoped `evidence_memo` cache, both mutated during a run."""

    settings: Settings
    workspace: Workspace
    sandbox: SandboxWorker
    run_id: str
    source: str
    memory: MemoryStore | None
    scanners: Sequence[Scanner] | None
    scan_sandbox: SandboxWorker | None
    project_brief: str
    project_context: str
    item_id: int | None
    test_cmd: Sequence[str] | None
    approve_writes: bool
    # The single shared mutable set: the coder's tools close over this exact object, and
    # author_tests_node fills it at runtime, so RunContext must hold the same instance.
    protected_tests: set[str]
    # The operator's write-gate approvals as facts the tamper guard reads (F63, #65): path -> the
    # integrity hash of content a HUMAN approved. Same shared-instance rule as protected_tests.
    operator_sanctioned: dict[str, str]
    # The coder's last engine-resolved `run_tests` output + the tree hash it was taken at (F70,
    # #75), so a hand-raise escalation — which never passes through `test` — can still name the
    # tests blocking it. Same shared-instance rule again; `capture_node` reads it and pins it.
    coder_validation: dict[str, str]
    # Slice 2.1: `sandbox_exec` degradation counts (timeout / truncated / unavailable), owned by
    # build_graph for the whole run and incremented by the tools. Same shared-instance rule as
    # `coder_validation` above; `capture_node` reads it into RunState so the ceiling question is
    # answerable from a stored card instead of an ephemeral stream.
    exec_degradations: dict[str, int]
    # Slice 2.1: the DENOMINATOR for the map above — `{"calls": n}`. Separate from the
    # degradation counts so no reader can mistake "the probe was used" for "the probe fell
    # short"; a zero degradation count is unreadable without it.
    exec_usage: dict[str, int]
    # Within-run cached evidence (#23 / ADR-0003): (tree_hash, …)-keyed memo, run-scoped.
    evidence_memo: dict[tuple[str, ...], Any]
    # All agent construction/invocation lives behind this injected bundle (the ONE
    # core→agents seam, mosaera_core.agents_bridge) — graph.py imports no agents package.
    agents: AgentTeam
    max_iter: int
    max_escalations: int
    max_reason: int
    # The project this run belongs to, when it is project-scoped — lets the scoping path load the
    # durable project map (#42, ADR-0047 §2). None for a CLI/repo run with no project (→ cold look).
    # Defaulted so direct constructions (tests) and non-project callers need not pass it.
    project_id: str | None = None
