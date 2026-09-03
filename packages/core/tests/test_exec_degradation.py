"""`sandbox_exec` says when it fell short, and the shortfall is counted (slice 2.1).

Slice 2's goal is *"close the largest MEASURED harness gap"* — and it was not measured. Reading the
shipped code, the probe's ceilings (30 s / 4 KB / 5 repeats / 25 calls) degraded like this:

| degradation | visible to the coder? | recorded? |
|---|---|---|
| output truncated | yes — `combined_output` appends a marker | **no** |
| **timed out**    | **NO** — partial output, no marker at all | **no** |
| unavailable      | yes — an explanatory string | **no** (returned before any telemetry) |

The timeout row is a correctness bug, not missing telemetry: `outcome.ok` was False and the return
path ignored it, so the coder could read a half-finished probe as the complete answer and conclude
the opposite of the truth — the tool misleading its own user.

Nothing reached a durable record either: `emit_activity` writes to the ephemeral LangGraph stream,
which is gone after the run. So *"does the 30 s ceiling actually bind?"* had no answer, and raising
it would have been a guess — the F83 mistake this session already made twice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mosaera_core.progress import fingerprint
from mosaera_core.sandbox import SandboxResult, SandboxViolation
from mosaera_core.tools.repo._exec import (
    EXEC_OUTPUT_LIMIT,
    EXEC_REPEAT_LIMIT,
    EXEC_SESSION_LIMIT,
    EXEC_TIMEOUT_S,
    build_sandbox_exec,
)


def _result(**over: Any) -> SandboxResult:
    base: dict[str, Any] = {
        "exit_code": 0,
        "stdout": "ok",
        "stderr": "",
        "duration_s": 0.1,
        "timed_out": False,
        "network_isolated": True,
    }
    base.update(over)
    return SandboxResult(**base)


class _Sandbox:
    def __init__(self, result: SandboxResult | None = None, raises: bool = False) -> None:
        self._result = result or _result()
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def run(self, argv: Any, **kw: Any) -> SandboxResult:
        self.calls.append(kw)
        if self.raises:
            raise SandboxViolation("no read-only support")
        return self._result


class _WS:
    # A Path, like the real `Workspace.root` — not a str. It points nowhere on purpose: these
    # tests are about the ceilings, and a missing `.venv` simply falls the probe back to the
    # engine interpreter (F87), which is what every case here expects.
    root = Path("/nonexistent")


def _probe(sandbox: Any, sink: dict[str, int] | None = None) -> Any:
    return build_sandbox_exec(_WS(), sandbox, fingerprint, sink)


def _run(tool: Any, code: str = "print(1)") -> str:
    return tool.invoke({"code": code})


# --- D1: the correctness fix ---------------------------------------------------------------


def test_a_timed_out_probe_says_so_before_its_partial_output() -> None:
    """THE correctness fix. A half-finished probe must never read as the complete answer.

    The marker goes FIRST: a coder skimming a wall of output must not have to reach the end to
    learn that what it is reading is partial.
    """
    sink: dict[str, int] = {}
    out = _run(_probe(_Sandbox(_result(timed_out=True, stdout="partial data")), sink))
    assert out.startswith("TIMED OUT")
    assert "PARTIAL" in out
    assert "partial data" in out, (
        "the partial output is still shown — it is evidence, just labelled"
    )
    assert out.index("TIMED OUT") < out.index("partial data")
    assert sink == {"timeout": 1}


def test_a_normal_probe_is_unchanged() -> None:
    """The no-degradation path must be byte-identical to before — this is a tool the coder uses
    constantly, and a marker on a healthy probe would be noise."""
    sink: dict[str, int] = {}
    assert _run(_probe(_Sandbox(_result(stdout="hello")), sink)) == "hello"
    assert sink == {}


def test_an_empty_result_still_says_so() -> None:
    assert _run(_probe(_Sandbox(_result(stdout="")))) == "(the snippet produced no output)"


# --- D3: the degradations are counted ------------------------------------------------------


def test_truncated_output_is_counted() -> None:
    sink: dict[str, int] = {}
    out = _run(_probe(_Sandbox(_result(stdout="x" * (EXEC_OUTPUT_LIMIT + 500))), sink))
    assert "truncated at" in out, "truncation self-reports — that part already worked"
    assert sink == {"truncated": 1}


def test_an_unavailable_backend_is_counted() -> None:
    """This path returned BEFORE any telemetry, so "the probe never ran" left no trace at all —
    the degradation most easily mistaken for "the coder never tried"."""
    sink: dict[str, int] = {}
    out = _run(_probe(_Sandbox(raises=True), sink))
    assert "unavailable" in out
    assert sink == {"unavailable": 1}


def test_the_two_budget_stops_are_counted() -> None:
    sink: dict[str, int] = {}
    tool = _probe(_Sandbox(), sink)
    for _ in range(EXEC_REPEAT_LIMIT + 1):
        _run(tool, "print(1)")
    assert sink.get("repeat_limit") == 1

    # Snippets must differ by LETTERS, not digits. Writing this with `print(0)`, `print(1)`, ...
    # made the repeat guard fire 20 times on "different" probes: `fingerprint` strips digits, so
    # they are all one snippet to it. That is the documented weakness (red-team #55) the TOTAL
    # session cap exists to backstop — demonstrated here by accident, so it is pinned on purpose.
    sink2: dict[str, int] = {}
    tool2 = _probe(_Sandbox(), sink2)
    for i in range(EXEC_SESSION_LIMIT + 1):
        _run(tool2, f"print('{chr(97 + i)}')")
    assert sink2.get("session_limit") == 1
    assert "repeat_limit" not in sink2, "letter-varied snippets must not look identical"


def test_the_fingerprint_strips_digits_so_the_total_cap_is_load_bearing() -> None:
    """Red-team #55's finding, pinned: cosmetic digit variation evades the repeat guard.

    `print(1)` and `print(2)` share a fingerprint, so a coder varying only numbers keeps hitting
    the repeat cap rather than escaping it — but a coder varying LETTERS escapes it entirely, which
    is why the hard TOTAL budget, not the repeat guard, is what actually bounds container cost.
    """
    sink: dict[str, int] = {}
    tool = _probe(_Sandbox(), sink)
    for i in range(EXEC_REPEAT_LIMIT + 2):
        _run(tool, f"print({i})")  # digits only — one probe as far as the fingerprint is concerned
    assert sink.get("repeat_limit", 0) >= 1


def test_counting_is_optional_and_never_breaks_the_tool() -> None:
    """The sink is caller-owned and may be absent (direct unit use, the tester's toolset).
    Telemetry must never be load-bearing."""
    assert _run(_probe(_Sandbox(_result(timed_out=True)), None)).startswith("TIMED OUT")


def test_two_runs_do_not_pollute_each_other() -> None:
    """A caller-owned map rather than a module global: two concurrent runs in one process must not
    share counts. A global here would silently merge unrelated runs' evidence."""
    a: dict[str, int] = {}
    b: dict[str, int] = {}
    _run(_probe(_Sandbox(_result(timed_out=True)), a))
    assert a == {"timeout": 1}
    assert b == {}


# --- the containment ADR-0059 established is NOT what "raise the ceiling" meant --------------


def test_the_probe_is_still_mounted_read_only() -> None:
    """The load-bearing property of ADR-0059: the probe can import and run repo code but never
    persists, so it cannot bypass the write gate, `protected_paths` or the tamper guard. Slice 2.1
    touches ceilings; it must never touch this."""
    sandbox = _Sandbox()
    _run(_probe(sandbox))
    assert sandbox.calls[0]["readonly_work"] is True
    assert sandbox.calls[0]["timeout"] == EXEC_TIMEOUT_S


def test_an_unenforceable_backend_still_fails_closed() -> None:
    """The subprocess backend cannot enforce read-only, so the tool reports itself unavailable
    rather than ever running writable. Recording the degradation must not have turned this into a
    fallback."""
    out = _run(_probe(_Sandbox(raises=True)))
    assert "unavailable" in out and "Use run_tests" in out


# --- The DENOMINATOR (added 2026-08-10) ----------------------------------------------------
#
# The first 52-run integration sweep recorded ZERO exec degradations, and the number could not be
# read: "the 30s/4KB ceiling does not bind on this corpus" and "the coder barely called the probe"
# produce the same zero. A count with no denominator is not a measurement — and deciding whether a
# ceiling is worth raising is this slice's whole stated purpose.


def test_every_real_probe_is_counted() -> None:
    usage: dict[str, int] = {}
    probe = build_sandbox_exec(_WS(), _Sandbox(), fingerprint, {}, usage)
    for _ in range(3):
        _run(probe, "print(1)")
    assert usage == {"calls": 3}


def test_a_healthy_probe_counts_WITHOUT_registering_a_degradation() -> None:
    """The whole point of two maps. A run that used the probe happily must read as
    'called, never degraded' — not as degraded, and not as never called."""
    sink: dict[str, int] = {}
    usage: dict[str, int] = {}
    _run(build_sandbox_exec(_WS(), _Sandbox(_result(stdout="hello")), fingerprint, sink, usage))
    assert sink == {}, "nothing degraded"
    assert usage == {"calls": 1}, "but the probe WAS exercised"


def test_a_degraded_probe_lands_in_both_so_a_RATE_is_derivable() -> None:
    sink: dict[str, int] = {}
    usage: dict[str, int] = {}
    probe = build_sandbox_exec(
        _WS(), _Sandbox(_result(timed_out=True, stdout="partial")), fingerprint, sink, usage
    )
    _run(probe, "print(1)")
    _run(probe, "print(2)")
    assert usage["calls"] == 2
    assert sink["timeout"] == 2, "2 of 2 — a rate, which the numerator alone could never give"


def test_an_empty_snippet_is_not_a_probe() -> None:
    """Counted after the empty-snippet guard: inflating the denominator would understate the
    degradation rate, the one direction that makes a ceiling look safer than it is."""
    usage: dict[str, int] = {}
    assert _run(build_sandbox_exec(_WS(), _Sandbox(), fingerprint, {}, usage), "   ").startswith(
        "ERROR"
    )
    assert usage == {}


def test_the_denominator_is_optional_and_never_breaks_the_tool() -> None:
    assert _run(build_sandbox_exec(_WS(), _Sandbox(_result(stdout="x")), fingerprint)) == "x"
