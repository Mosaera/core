"""A parked run must say WHY it is asking, at the moment it asks (F78, 2026-08-23).

``build_diagnosis`` ran on terminal paths only — after the stream completes, and on
cancel/timeout/crash. A run parked at an interrupt is neither, so ``diagnosis`` was ``null``
exactly when a human is being asked to decide and the run page fell back to listing what the gate
could not find.

Measured live: three LedgerCLI runs went ``plan -> gate`` instantly, and the page read "no checks
were attempted / the reviewer's verdict couldn't be read / the run ended before the security scan
could run". None of those name the cause. State held ``plan_unworkable_reason: under_specified: no
material acceptance claim is checkable as written`` the whole time, and the only way to reach it was
the API. Both halves of the vocabulary already existed (``_STOP_CHANNELS`` server-side,
``STOP_CHANNELS`` + ``PARK_CAUSE.under_specified`` in the SPA) — nothing wrote the record here.

Exercised as the unbound method over a minimal stand-in: this pins the shipped code path without
standing up a whole RunSession, and keeps the assertion on the one behaviour that was missing.
"""

from __future__ import annotations

import time
from typing import Any, cast

from mosaera_api.runner._loop import LoopMixin

_UNDER_SPECIFIED = "under_specified: no material acceptance claim is checkable as written"


class _FakeMemory:
    def __init__(self) -> None:
        self.diagnoses: dict[str, dict[str, Any]] = {}

    def record_run_diagnosis(self, run_id: str, diagnosis: dict[str, Any]) -> None:
        self.diagnoses[run_id] = diagnosis


class _FakeGraph:
    """``get_state(...).values`` is the whole surface the pause path reads."""

    def __init__(self, values: dict[str, Any] | None, *, raises: bool = False) -> None:
        self._values = values or {}
        self._raises = raises

    def get_state(self, _config: Any) -> Any:
        if self._raises:
            raise RuntimeError("checkpointer unavailable")
        return type("S", (), {"values": self._values})()


class _Stub:
    """The attributes ``_record_pause_diagnosis`` touches, and nothing else."""

    def __init__(self, values: dict[str, Any] | None, *, raises: bool = False) -> None:
        self.run_id = "run-1"
        self._memory: Any = _FakeMemory()
        self._graph = _FakeGraph(values, raises=raises)
        self._config: dict[str, Any] = {}
        self._max_iterations = 3
        self.evidence_home = ""
        self.diagnosis: Any = None
        self.audits: list[tuple[str, str]] = []

    def _audit(self, event: str, detail: str = "") -> None:
        self.audits.append((event, detail))

    def _safe(self, fn: Any) -> None:
        try:
            fn()
        except Exception:  # noqa: S110 — mirrors the real best-effort persistence
            pass


def _park(values: dict[str, Any] | None, **kw: Any) -> _Stub:
    stub = _Stub(values, **kw)
    LoopMixin._record_pause_diagnosis(stub)  # type: ignore[arg-type]
    return stub


def test_the_recorded_reason_reaches_the_operator() -> None:
    """The exact live failure: the cause existed in state and nothing surfaced it."""
    stub = _park({"plan_unworkable_reason": _UNDER_SPECIFIED})

    assert stub.diagnosis is not None, "a parked run with a recorded cause must carry a diagnosis"
    assert stub.diagnosis["plan_unworkable_reason"] == _UNDER_SPECIFIED
    assert stub._memory.diagnoses["run-1"]["plan_unworkable_reason"] == _UNDER_SPECIFIED


def test_the_pause_record_is_marked_provisional() -> None:
    """So a reader can tell "this is why it is asking" from "this is how it ended" — the terminal
    diagnosis overwrites it when the run settles."""
    assert _park({"plan_unworkable_reason": _UNDER_SPECIFIED}).diagnosis["provisional"] is True


def test_every_stop_channel_survives_the_pause_not_just_the_plan_one() -> None:
    """The park that started this arc had no record at all, and the over-park of 2026-08-05 was
    permanently unattributable for the same reason. Pin the channels, not one example."""
    for key in ("stall_reason", "give_up_reason", "blocked_reason", "escalate_reason"):
        assert _park({key: "because"}).diagnosis[key] == "because", key


def test_a_pause_with_nothing_recorded_still_writes_a_record() -> None:
    """Absence has to be a written absence: "we looked and state said nothing" is a different
    claim from "nobody wrote anything down", and only the first is reconstructable later."""
    stub = _park({})
    assert stub.diagnosis is not None
    assert stub._memory.diagnoses["run-1"]["provisional"] is True


def test_an_unreadable_checkpoint_never_breaks_the_park() -> None:
    """Best-effort by construction — a diagnosis must never break the pause it describes."""
    stub = _park(None, raises=True)
    assert stub.diagnosis is None
    assert stub._memory.diagnoses == {}


def test_no_memory_is_a_no_op() -> None:
    stub = _Stub({"plan_unworkable_reason": _UNDER_SPECIFIED})
    stub._memory = None
    LoopMixin._record_pause_diagnosis(stub)  # type: ignore[arg-type]
    assert stub.diagnosis is None


# --------------------------------------------------------------------- the wiring itself


def test_reaching_a_park_records_the_diagnosis() -> None:
    """The pin that the method-level tests above CANNOT provide.

    Deleting the `_record_pause_diagnosis()` call at the park site leaves every test above green —
    they exercise the method directly. A pin that survives the removal of the thing it guards is
    the "pin that cannot fail" this repo keeps paying for, so this one drives the real loop to a
    real interrupt and asserts a record exists at the moment the run starts waiting.
    """
    from mosaera_api.runner import RunSession
    from test_api import _build_fake_graph  # the shared plan->gate->deliver fake

    memory = _FakeMemory()
    session = RunSession(
        "park-wiring",
        _build_fake_graph(max_iterations=1),
        {"configurable": {"thread_id": "park-wiring"}},
        # A blocking signal so the gate parks for a human instead of delivering.
        {"task": "x", "tests_passed": False},
        auto_approve=False,
        memory=cast(Any, memory),
    )
    session.start()
    for _ in range(200):
        if session.status == "awaiting_approval":
            break
        time.sleep(0.05)

    assert session.status == "awaiting_approval", "the run never reached the park"
    assert "park-wiring" in memory.diagnoses, "a parked run recorded no diagnosis"
    assert memory.diagnoses["park-wiring"]["provisional"] is True
