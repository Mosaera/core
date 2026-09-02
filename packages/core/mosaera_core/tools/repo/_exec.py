"""`sandbox_exec` — the coder's read-only probe (ADR-0059), and its ceilings.

Split out of ``factory.py`` on 2026-08-09 for the god-file guard, the same reason `_read`,
`_scratch` and `_activity` were. The split is not incidental here: this tool is the one place a
ceiling decides how much the coder can observe, and slice 2.1 needed room to record when a ceiling
BOUND — which is a different question from what the tool returns.

**The containment is ADR-0059's and is not this module's to relax.** `readonly_work=True` mounts
the workspace `:ro`, so the probe can import and run repo code but never persists — it cannot
bypass the write-approval gate, `protected_paths` or the ADR-0036 tamper guard. Network stays off.
The subprocess backend cannot enforce read-only, so it **fails closed** and the tool reports itself
unavailable rather than ever running writable.

The ceilings below are quick-by-design (a probe, not a build). What changed in slice 2.1 is only
that falling short of one is now *recorded*: `emit_activity` writes to the ephemeral LangGraph
stream, which reaches no checkpoint and no scorecard, so *"does the 30s / 4KB ceiling actually
bind?"* had no answer at all — and raising a ceiling nobody had measured would have been a guess.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from mosaera_core.languages.python import project_interpreter
from mosaera_core.sandbox import SandboxViolation
from mosaera_core.tools.repo._activity import emit_activity, note_degradation
from mosaera_core.tools.repo._envfacts import environment_facts

# Quick by design (probe, not a build); output capped like a validation step; the same snippet
# re-run past this many times this session is looping, not converging, so it gets the STOP
# directive (mirrors the run_tests repeat guard).
EXEC_TIMEOUT_S = 30
EXEC_OUTPUT_LIMIT = 4_000
EXEC_REPEAT_LIMIT = 5
# Hard TOTAL probe budget per run — bounds container cost even if the coder varies the snippet to
# dodge the identical-snippet guard (red-team #55). Generous: a probe should converge well under it.
EXEC_SESSION_LIMIT = 25


def build_sandbox_exec(
    workspace: Any,
    sandbox: Any,
    fingerprint: Any,
    exec_degradations: dict[str, int] | None = None,
    exec_usage: dict[str, int] | None = None,
    env_facts_seen: dict[str, str] | None = None,
) -> Any:
    """The `sandbox_exec` tool, with its per-run counters closed over.

    ``exec_degradations`` is the caller-owned map (see `_activity.note_degradation`): counts reach
    RunState through it, so the ceiling question can be answered from a stored card.

    ``exec_usage`` is the **denominator**, and it is a SEPARATE map on purpose. Slice 2.1 shipped
    counting only the ways the probe fell short, and the first 52-run sweep returned zero
    degradations — a number nobody could read, because *"the 30s/4KB ceiling does not bind"* and
    *"the coder barely called the probe"* produce the same zero. A count with no denominator is not
    a measurement, and deciding whether a ceiling is worth raising is this slice's whole purpose.

    Kept apart from ``exec_degradations`` rather than riding a reserved key in it: every reader
    would then have to filter, and *"any key means something degraded"* is precisely the implicit
    coupling that left slice 3 reading state that was never there. A separate map cannot be
    misread.
    """
    fp_counts: dict[str, int] = {}
    calls = [0]

    def _note(kind: str) -> None:
        note_degradation(exec_degradations, kind)

    @tool
    def sandbox_exec(code: str) -> str:
        """Run a short PYTHON snippet in the sandbox to OBSERVE behaviour — import the repo's
        modules and print what they actually return or output — instead of writing throwaway debug
        scripts. Use this when a test fails and you need to see the EXACT value your code produces
        (e.g. `from pkg.mod import f; print(repr(f(x)))`). The workspace is READ-ONLY here: you can
        run and import code but CANNOT create or change files (write scratch data under /tmp). There
        is no network. Returns the snippet's stdout + stderr."""
        if not code.strip():
            return "ERROR: sandbox_exec needs a non-empty Python snippet."
        # TOTAL probe budget per run (red-team #55): the identical-snippet guard below shares the
        # run_tests digit-stripping-fingerprint weakness (cosmetic variation — a renamed var or a
        # letter comment — evades it), so a hard TOTAL cap bounds the container cost regardless of
        # how the coder varies the snippet. A probe should converge in a handful of tries.
        calls[0] += 1
        # The denominator, counted AFTER the empty-snippet guard: an invocation that never reached
        # the sandbox is not a probe, and inflating the denominator would understate the degradation
        # rate — the one direction that makes a ceiling look safer than it is.
        note_degradation(exec_usage, "calls")
        if calls[0] > EXEC_SESSION_LIMIT:
            _note("session_limit")
            return (
                f"STOP — sandbox_exec has run {EXEC_SESSION_LIMIT} times this run; probing isn't "
                "resolving it. Make an edit, or reply 'SUMMARY: blocked — <the blocker>'."
            )
        # A coder re-running the SAME probe isn't learning anything new — cap it (like run_tests).
        fp = fingerprint("exec", code)
        n = fp_counts.get(fp, 0) + 1
        fp_counts[fp] = n
        if n > EXEC_REPEAT_LIMIT:
            _note("repeat_limit")
            return (
                f"STOP — you have run this exact snippet {n} times this session. Change your "
                "approach (a different probe, or edit the code) rather than re-running it."
            )
        try:
            # -B: don't try to write .pyc into the read-only /work. readonly_work=True mounts the
            # workspace :ro so the probe can import + run repo code but never persists (ADR-0059).
            outcome = sandbox.run(
                # F87: the PROJECT's interpreter, not the engine's. `sys.executable` cannot
                # import a `pip install -e .` package — it lives in the validation venv — so the
                # probe contradicted the suite and the coder believed the probe.
                [project_interpreter(workspace), "-B", "-c", code],
                cwd=workspace.root,
                timeout=EXEC_TIMEOUT_S,
                readonly_work=True,
            )
        except SandboxViolation:
            # The subprocess backend can't enforce read-only /work → the probe is unavailable there
            # (fail-closed; never writable). Recorded: this path returned before ANY telemetry, so
            # "the probe never ran" was the degradation most easily mistaken for "it didn't try".
            emit_activity("sandbox_exec", "", "unavailable (cannot enforce read-only)")
            _note("unavailable")
            return (
                "sandbox_exec is unavailable on this sandbox backend — it needs the Docker sandbox "
                "for read-only isolation. Use run_tests to check behaviour."
            )
        out = outcome.combined_output(limit=EXEC_OUTPUT_LIMIT)
        if out.rstrip().endswith(f"(truncated at {EXEC_OUTPUT_LIMIT} chars)"):
            _note("truncated")
        if outcome.timed_out:
            # A timed-out probe used to return its PARTIAL output with nothing saying so: `ok` was
            # False and this path ignored it, so the coder could read a half-finished probe as the
            # complete answer and conclude the opposite of the truth — the tool misleading its own
            # user. Truncation already self-reports; a timeout did not. Stated FIRST so it cannot
            # be missed under a wall of output.
            _note("timeout")
            emit_activity("sandbox_exec", "", f"TIMED OUT at {EXEC_TIMEOUT_S}s")
            return (
                f"TIMED OUT after {EXEC_TIMEOUT_S}s — the snippet did not finish, so the output "
                f"below is PARTIAL and may be misleading. Probe something smaller.\n\n{out}"
            )
        emit_activity("sandbox_exec", "", "ok" if outcome.ok else f"exit {outcome.exit_code}")
        body = out or "(the snippet produced no output)"
        # ADR-0110 slice 1. On FAILURE only, and keyed on the exit code rather than on any
        # particular symptom: `_uninstalled_note` matched one misdiagnosis (import failure with no
        # venv), and the producer has since invented others. A general trigger cannot go stale the
        # way a detector list does, which is what ADR-0085 §1 froze.
        return (environment_facts(workspace, env_facts_seen) if not outcome.ok else "") + body

    return sandbox_exec
