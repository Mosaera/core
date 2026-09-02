"""Shared infrastructure + module-level helpers for the RunSession package.

``RunSessionBase`` holds the ``RunSession`` constructor, the shared mutable
run-state attributes, and the small helpers that don't belong to a single
concern (the simple accessors, ``_emit``/``_emit_thought``/``_audit``,
``_checkpoint``, ``_persist_cost``, ``_safe``). The focused per-concern mixins
(lifecycle, budget, loop) inherit it for their shared state and for typing.

This module also owns the module-level helpers (``_revision_feedback``,
``json_safe``, ``_keep``, ``_activity``), the run
exceptions (``RunCancelled``, ``RunTimeout``), and the shared constants.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import mosaera_core
from mosaera_core.config import Settings
from mosaera_core.cost import CostMeter, UsageCallback
from mosaera_core.persist import claim_rows, make_receipt_id, receipt_json
from mosaera_core.run_diagnosis import build_diagnosis, diagnosis_summary
from mosaera_memory import MemoryStore

from mosaera_api.reasoning import ReasoningCallback

_JSON_SCALARS = (str, int, float, bool, type(None))

# Event types worth persisting to the durable transcript (the fine-grained progress
# the SPA reconstructs). Lifecycle/control events (_end, done, error) are excluded.
_DURABLE_EVENT_TYPES = frozenset({"activity", "thought", "update", "interrupt", "escalation"})

# The SETTLED terminal run statuses. `incomplete` (ADR-0006 — the honest non-delivery
# outcome) is a first-class member: omitting it here is how a session leak / a never-ending
# SSE stream / a rehydrate hang creep in. Defined ONCE and reused (session reap, stream-end,
# rehydrate) so a future status can't be added to some copies and missed in others.
TERMINAL_STATUSES = frozenset({"completed", "incomplete", "error", "cancelled"})

# Poison sentinel: unblocks a worker parked on the resume queue when the run
# is cancelled (nothing else can — approve() rejects non-awaiting sessions).
_CANCELLED = object()


class RunCancelled(Exception):
    """Raised inside the worker when a cancel signal is observed."""


class RunTimeout(Exception):
    """Raised inside the worker when the wall-clock cap is exceeded."""


def _revision_feedback(payload: dict[str, Any], reasons: list[str]) -> str:
    """Feedback the autonomous deny sends back to planning: the reviewer's
    notes (sans the VERDICT line), honestly attributed."""
    review = str(payload.get("review", ""))
    notes = "\n".join(line for line in review.splitlines() if "VERDICT" not in line.upper()).strip()
    prefix = f"autonomous: reviewer requested changes ({', '.join(reasons)})"
    return f"{prefix} — {notes[:800]}" if notes else prefix


def json_safe(value: Any) -> Any:
    """Reduce a node update to JSON-serializable data (drops message objects)."""
    if isinstance(value, _JSON_SCALARS):
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items() if _keep(k, v)}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value if isinstance(v, (*_JSON_SCALARS, dict, list))]
    return None


def _keep(key: Any, value: Any) -> bool:
    # Drop LangChain message channels and other non-serializable payloads.
    if key == "messages":
        return False
    return isinstance(value, (*_JSON_SCALARS, dict, list, tuple))


def _activity(data: Any) -> dict[str, Any] | None:
    """Normalize a coder tool's custom stream event into a milestone activity.

    Defensive: only our own ``{"activity": <kind>, "detail"?: <str>}`` shape
    passes through; anything else is ignored so a stray custom write can't
    poison the SSE stream.
    """
    if not isinstance(data, dict):
        return None
    kind = data.get("activity")
    if not isinstance(kind, str):
        return None
    out: dict[str, Any] = {"kind": kind}
    detail = data.get("detail")
    if isinstance(detail, str) and detail:
        out["detail"] = detail[:200]
    result = data.get("result")
    if isinstance(result, str) and result:
        out["result"] = result[:200]
    return out


class RunSessionBase:
    """Lifecycle: pending -> running -> awaiting_approval* -> a settled terminal status.

    The terminal statuses are ``TERMINAL_STATUSES`` = completed | incomplete | cancelled | error
    (``incomplete`` is the honest non-delivery outcome, ADR-0006).

    ``cancelling`` is the transient state between an HTTP cancel signal and the
    worker actually stopping (latency bounded by the current node's duration:
    model calls by the Ollama client timeout, sandbox commands by the sandbox
    timeout). The worker owns every terminal transition; HTTP threads only
    signal. The CLI has no session lifecycle — Ctrl-C is its cancel.
    """

    def __init__(
        self,
        run_id: str,
        graph: Any,
        config: dict[str, Any],
        initial: dict[str, Any] | None,
        memory: MemoryStore | None = None,
        project_id: str | None = None,
        item_id: int | None = None,
        on_done: Callable[[], None] | None = None,
        auto_approve: bool = False,
        on_park: Callable[[], None] | None = None,
        max_seconds: float | None = None,
        high_assurance: bool = False,
        mode: str = "guided",
        budget: dict[str, float] | None = None,
        hard_budget: dict[str, float] | None = None,
        prior_cost: dict[str, Any] | None = None,
        resilient: bool = False,
        max_iterations: int | None = None,
    ):
        self.run_id = run_id
        self.status = "pending"
        self.phase = ""  # current graph node (plan/implement/test/scan/review/gate/deliver)
        self.started_at = 0.0
        self.pending_interrupt: dict[str, Any] | None = None
        self.final: dict[str, Any] | None = None
        # Why a run ended without delivering (set when status becomes "incomplete");
        # None for a clean delivery, a human decision, cancel, or error.
        self.termination_reason: str | None = None
        # The STRUCTURED record of how this run ended (`mosaera_core.run_diagnosis`) — the same
        # outcome bucket and park cause the benchmark computes, so a live failure and a bench
        # failure are directly comparable. Before this, a live run recorded `termination_reason`
        # and nothing else, which made every observed failure an anecdote: no bucket, no park
        # cause, no gate reasons, no vouch. None until the run reaches a terminal state.
        self.diagnosis: dict[str, Any] | None = None
        # Standing operator corrections captured this run (F17). Surfaced because a constraint
        # that steers every later write while being invisible to the operator who set it is the
        # "unauditable, silently-accumulating influence" ADR-0084 rejects — and because its
        # absence made the 2026-08-06 failure undiagnosable from outside the process.
        self.corrections: list[str] = []
        # Authored tests that can never pass because they pin a value the test never supplied
        # (F36). Surfaced at authoring time; the run that found this one spent ~256k tokens and
        # eleven gates before an escalation revealed it.
        self.unsatisfiable_tests: list[dict[str, Any]] = []
        # The effective iteration cap, needed to tell an honest park from a ride-to-the-cap thrash
        # (#51/ADR-0056: the gate's `iteration_limit` reason never commits on a park, so the cap
        # must be compared against `final["iteration"]` directly). None keeps the pre-#51 reading.
        self._max_iterations = max_iterations
        self._graph = graph
        # Per-run cost/token accounting: attach a usage callback to the graph
        # config so LangGraph propagates it to every nested model call (PM,
        # coder, reviewer) — one attachment covers the whole pipeline. Prices
        # come from the UI-managed settings (env override) so $ stays current.
        _settings = Settings.from_env()
        # The control set THIS run executed with, captured at start and never re-read. A knob
        # flipped later must not retroactively re-describe a finished run — that would be a new
        # way for the dashboard to lie about history.
        #
        # It exists so the UI can show the full cast of agents and oracles from t=0, including the
        # ones that are switched OFF. Before this the roster was inferred from observed events, so
        # a disabled control was indistinguishable from one that simply hadn't run yet — which is
        # how `critic_enabled` sat at its highest proven liveness rung and OFF, unremarked, on the
        # live instance (2026-08-06).
        self.controls: dict[str, bool] = {
            "tester_enabled": _settings.tester_enabled,
            "critic_enabled": _settings.critic_enabled,
            "scan_enabled": _settings.scan_enabled,
            "oracle_coverage": _settings.oracle_coverage,
            "oracle_mutation_check": _settings.oracle_mutation_check,
            "reason_on_stall_enabled": _settings.reason_on_stall_enabled,
            "escalate_arm": _settings.escalate_arm,
        }
        # TM-0001: the absolute store this run writes to, recorded so a misdirected write is
        # visible afterwards. Resolved ONCE here — reading it later would resolve a different
        # cwd and defeat the point.
        self.evidence_home = str(_settings.home.resolve())
        self.cost_meter = CostMeter.for_settings(_settings)
        # Carry prior-session spend across a restart: a rehydrated run seeds its meter
        # from the last persisted rollup so budget/hard-cap math resumes from real
        # spend, not zero. No-op on a fresh run.
        self.cost_meter.seed(prior_cost)
        callbacks = list(config.get("callbacks") or [])
        callbacks.append(UsageCallback(self.cost_meter))
        # Stream each agent turn's reasoning to the transcript (same propagation the
        # usage callback rides). One block per model turn — never a token firehose.
        if _settings.stream_reasoning:
            callbacks.append(ReasoningCallback(self._emit_thought))
        self._config = {**config, "callbacks": callbacks}
        self._initial = initial
        self._memory = memory
        self._project_id = project_id
        self._item_id = item_id
        self._on_done = on_done
        self._auto_approve = auto_approve
        # High Assurance: auto-approve write gates like autonomous, but ALWAYS
        # park the delivery gate for a human — never auto-deliver, even clear.
        self._high_assurance = high_assurance
        self.mode = mode  # display only (guided | autonomous | high_assurance)
        # Resilient sweep (ADR-0023): when set, a chained autonomous run does NOT park-and-hold
        # the clone on blocking evidence at the DELIVERY gate — it ends honestly `incomplete` so
        # the sweep's _after can defer the item and keep delivering the rest.
        self._resilient = resilient
        # Stashed gate_decision when a resilient run gives up at the delivery gate (see the
        # terminal block) — restored into `final` so escalation can diagnose the bottleneck.
        self._resilient_gate: dict[str, Any] | None = None
        # Stashed (claims, claim_dispositions) from the same giveup payload (ADR-0078): the
        # graph never resumes past that interrupt, so deliver_node's persist never runs —
        # without this stash the receipt and claim ledger of a never-resumed park vanish.
        self._resilient_claims: tuple[list[Any], list[Any]] = ([], [])
        self._on_park = on_park
        self._max_seconds = max_seconds
        # Per-run spend ceilings {usd|tokens|tool_calls: cap}; a crossed ceiling
        # PARKS for approval (raise it and continue, or stop). Mutable: approving
        # a breach raises that dimension's cap so the run proceeds to the next one.
        self._budget = dict(budget) if budget else {}
        # Absolute HARD ceilings {usd|tokens: cap}: a crossed hard ceiling CANCELS the
        # run (not re-askable) — the backstop so a non-converging run can't be funded
        # forever. Immutable. Also how many times the soft budget has been raised, so
        # the park prompt can say "you've already raised this N times".
        self._hard_budget = dict(hard_budget) if hard_budget else {}
        self._budget_approvals = 0
        self._cancel = threading.Event()
        self._parked_seconds = 0.0  # gate-wait time excluded from the cap
        # SSE fan-out: every emitted event is appended to _history AND broadcast to
        # each connected subscriber's own queue, so N concurrent viewers each get the
        # FULL stream (a single shared queue would split events across them). A late
        # subscriber replays _history first. Run-scoped; freed when the session evicts.
        self._history: list[dict[str, Any]] = []
        self._subscribers: list[queue.Queue[dict[str, Any]]] = []
        self._events_lock = threading.Lock()
        # Monotonic per-run event sequence for the durable transcript (mirrors the
        # SSE arrival order the SPA reconstructs client-side).
        self._event_seq = 0
        self._resume: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._thread: threading.Thread | None = None
        # Gate-decision race guard: a park sets _awaiting_decision True; approve()/
        # cancel() atomically claim it under the lock so exactly ONE decision is
        # consumed per park. Without this, two concurrent approves both pass the
        # status check and the stale second decision leaks into the NEXT park.
        self._decision_lock = threading.Lock()
        self._awaiting_decision = False
        # Count of deterministic tool operations this run (file read/write/search/
        # list, validation) — the deterministic-first discipline metric (#22). It
        # rides into the durable cost rollup at finalize, so `det_ops : calls` (LLM)
        # is queryable per project without a new table. Seeded from prior spend on
        # a restart-rehydrated run so the ratio doesn't undercount.
        self._det_ops = int((prior_cost or {}).get("det_ops") or 0)

    # --- lifecycle ---

    @property
    def project_id(self) -> str | None:
        return self._project_id

    @property
    def item_id(self) -> int | None:
        return self._item_id

    @property
    def initial_task(self) -> str:
        return str((self._initial or {}).get("task", ""))

    def _record_corrections(self, update: Any) -> None:
        """Accumulate operator-facing findings as node deltas stream past.

        Deduped and order-preserving: `corrections` uses an `add` reducer, so the same rule can
        legitimately arrive twice (from the Proctor's delta and from the coder) and the operator
        should see it once.
        """
        if not isinstance(update, dict):
            return
        for item in update.get("corrections") or []:
            text = str(item).strip()
            if text and text not in self.corrections:
                self.corrections.append(text)
        for finding in update.get("unsatisfiable_tests") or []:
            if isinstance(finding, dict) and finding not in self.unsatisfiable_tests:
                self.unsatisfiable_tests.append(finding)

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "phase": self.phase,
            "mode": self.mode,
            "started_at": self.started_at or None,
            "pending_interrupt": self.pending_interrupt,
            "approved": bool(self.final.get("approved")) if self.final else None,
            "report_path": (self.final or {}).get("report_path"),
            "commit_sha": (self.final or {}).get("commit_sha"),
            "termination_reason": self.termination_reason,
            "diagnosis": self.diagnosis,
            "cost": self.cost_meter.rollup(),
            "budget": dict(self._budget) or None,
            "corrections": list(self.corrections),
            "unsatisfiable_tests": list(self.unsatisfiable_tests),
            "controls": dict(self.controls),
        }

    def transcript_events(self) -> list[dict[str, Any]]:
        """The in-memory transcript in the durable shape — a fallback for the
        transcript API when nothing was persisted (the in-memory store, or a run
        still live in this process)."""
        with self._events_lock:
            history = list(self._history)
        out: list[dict[str, Any]] = []
        seq = 0
        for ev in history:
            if ev["type"] not in _DURABLE_EVENT_TYPES:
                continue
            data = ev["data"] if isinstance(ev["data"], dict) else {}
            seq += 1
            out.append(
                {
                    "seq": seq,
                    "type": ev["type"],
                    "node": data.get("node"),
                    "ts": int(data.get("ts") or 0),
                    "data": data,
                }
            )
        return out

    # --- worker ---

    def _checkpoint(self) -> None:
        """Between-chunk stop check: cancellation and the wall-clock cap.

        The cap bounds EXECUTION time: time parked at an approval gate is
        excluded, so a human deliberating for an hour never earns the run an
        instant timeout the moment they approve.
        """
        if self._cancel.is_set():
            raise RunCancelled
        if self._max_seconds and self.started_at:
            executing = time.time() - self.started_at - self._parked_seconds
            if executing > self._max_seconds:
                raise RunTimeout(f"wall-clock cap exceeded ({int(self._max_seconds)}s)")

    def _persist_cost(self) -> None:
        """Write the current token/cost rollup (incl. det_ops) as a durable `cost`
        decision. Idempotent-ish: reads take the newest row, so calling it at every
        park and again at finalize records cumulative spend without double-counting."""
        if self._memory is None:
            return
        rollup = self.cost_meter.rollup()
        rollup["det_ops"] = self._det_ops
        if rollup["calls"] > 0:
            self._safe(lambda: self._memory.add_decision(self.run_id, "cost", json.dumps(rollup)))

    def _persist_receipt(self) -> None:
        """ADR-0078 capture: durably write the receipt + claim ledger of a run whose
        parking gate visit never resumed (the resilient giveup breaks AT the interrupt,
        so deliver_node's persist never runs). Uses the stashed interrupt payload; the
        mutation tri-state comes from committed state (it precedes the gate). Dedupe is
        belt-and-braces: claims are only written when the ledger is still empty."""
        if self._memory is None or not self._resilient_gate:
            return
        memory = self._memory
        gate = {
            **self._resilient_gate,
            "tests_mutation_caught": (self.final or {}).get("tests_mutation_caught"),
        }
        payload = receipt_json({"gate_decision": gate})
        if payload:
            self._safe(lambda: memory.add_decision(self.run_id, "receipt", payload))
            # Seal the never-resumed park too (#63): deliver_node's record_run won't run,
            # so stamp engine_version + the deterministic receipt id here. A giveup never
            # commits, so the seal's commit_sha component is honestly empty.
            rid = make_receipt_id(self.run_id, "", mosaera_core.__version__, payload)
            self._safe(
                lambda: memory.stamp_run_receipt(
                    self.run_id, engine_version=mosaera_core.__version__, receipt_id=rid
                )
            )
        claims, dispositions = self._resilient_claims
        if claims:
            rows = claim_rows(claims, dispositions)

            def _write_claims() -> None:
                if not memory.list_run_claims(self.run_id):
                    memory.add_run_claims(self.run_id, rows)

            self._safe(_write_claims)

    def _emit(self, type_: str, data: Any) -> None:
        # Stamp a SERVER timestamp (epoch ms) so the transcript can show when each
        # step happened and how long each agent worked — correct even when the SSE
        # replays the whole history to a late subscriber (client receive-time would
        # cluster every replayed event at "now"). Concurrency-ready: each event
        # carries its own time, so overlapping agents show overlapping timestamps.
        if isinstance(data, dict) and "ts" not in data:
            data = {**data, "ts": int(time.time() * 1000)}
        event = {"type": type_, "data": data}
        with self._events_lock:
            self._history.append(event)
            for sub in self._subscribers:
                sub.put(event)
        # Durable transcript: persist the fine-grained progress events best-effort,
        # OUTSIDE the fan-out lock so a slow DB write never stalls the live stream.
        if self._memory is not None and type_ in _DURABLE_EVENT_TYPES and isinstance(data, dict):
            self._event_seq += 1
            seq, node = self._event_seq, data.get("node")
            ts, payload = int(data.get("ts") or 0), json.dumps(data)
            self._safe(
                lambda: self._memory.add_run_event(self.run_id, seq, type_, node, ts, payload)
            )

    def _emit_thought(self, node: str | None, text: str) -> None:
        """Sink for the reasoning callback: stream one agent turn's thinking as a
        `thought` event (truncated), attributed to the node that produced it."""
        text = text.strip()
        if not text:
            return
        if len(text) > 2000:
            text = text[:2000] + "\n… (truncated)"
        self._emit("thought", {"node": node or self.phase or "implement", "text": text})

    def _audit(self, event: str, detail: str = "") -> None:
        if self._memory is not None:
            self._safe(lambda: self._memory.add_audit_event(self.run_id, event, detail))

    def _record_terminal_diagnosis(self, how: str, *, errored: bool = False) -> None:
        """Record WHY a run ended when it ended abnormally — cancelled, timed out, crashed.

        The normal path builds a diagnosis after the stream completes. None of the abnormal exits
        reach it, so a run that was cancelled recorded `status=CANCELLED` and nothing else.

        Measured 2026-08-06: all 11 LedgerCLI runs were cancelled, so the project's ENTIRE history
        was diagnostically blank — and when the PM was finally given run evidence to read (F47) it
        correctly reported "the engine recorded no diagnosis", then filled the silence with a wrong
        causal story anyway. The honest-absence line only helps when absence is rare; here it was
        universal. A cancel is the most common way an operator ends a stuck run, which makes it the
        case we can least afford to lose.

        Best-effort by construction: the graph state may be partial (a cancel can land
        anywhere), so this reads whatever exists and records that. Partial evidence beats none;
        `how` distinguishes it from a run that concluded on its own.
        """
        if self._memory is None:
            return
        final: dict[str, Any] = {}
        try:  # a cancel can land before the graph has any state at all
            final = dict(self._graph.get_state(self._config).values)
        except Exception:  # a stateless cancel still records how it ended
            final = dict(self.final or {})
        try:
            diagnosis = build_diagnosis(
                final,
                errored=errored,
                max_iterations=self._max_iterations,
                evidence_home=self.evidence_home,
            )
        except Exception:  # never let diagnosis-building break the exit path
            return
        # Stamped so a reader can tell "the operator stopped it here" from "it concluded".
        diagnosis["ended_by"] = how
        self.diagnosis = diagnosis
        self._audit("diagnosis", f"{how}: {diagnosis_summary(diagnosis)}")
        self._safe(lambda: self._memory.record_run_diagnosis(self.run_id, diagnosis))

    @staticmethod
    def _safe(fn: Any) -> None:
        try:
            fn()
        except Exception:  # noqa: S110 — persistence is best-effort; never break a run
            pass

    if TYPE_CHECKING:
        # Type-only declarations of the sibling-mixin methods that the helpers here
        # (and each mixin) call via ``self``. They are defined at runtime by the
        # concrete mixins composed into ``RunSession`` — these stubs only give mypy
        # the shared surface so each mixin type-checks in isolation.
        def _run(self) -> None: ...
        def _enter_awaiting(self, interrupt: dict[str, Any]) -> None: ...
        def _budget_breach(self) -> tuple[str, float, float] | None: ...
        def _hard_breach(self) -> tuple[str, float, float] | None: ...
        def _cancel_hard(self, breach: tuple[str, float, float]) -> None: ...
        def _park_budget(self, breach: tuple[str, float, float]) -> None: ...
        def _resolve_escalation(self, intr: Any, value: dict[str, Any]) -> dict[str, Any]: ...
