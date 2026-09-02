"""Validation Planner: deterministic, manifest-based validation for a run.

Replaces the old hardcoded ``pytest -q`` default. The planner inspects the
workspace (manifests + file listing), picks REAL offline checks the sandbox
can actually run, and reports an honest tri-state:

- ``passed=True``  — every planned step succeeded (real evidence, printed).
- ``passed=False`` — a planned step failed or timed out.
- ``passed=None``  — no honest validation is possible (e.g. a JavaScript
  project in the network-less sandbox); the reason says exactly why. The
  delivery gate treats this as ``validation_unavailable`` and parks
  autonomous runs for a human.

No LLM is involved anywhere in this path: generated tests are the kind of
unreliable signal the gate exists to reject. Every plan is user-visible —
in the gate payload, the run report, persisted rows, and the Runs panel.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # runtime import would cycle: tools.repo imports this module
    from mosaera_core.sandbox import SandboxWorker
    from mosaera_core.tools.repo import Workspace

_MAX_HTML_FILES = 20
_MAX_MANIFEST_READ = 200_000
_STEP_OUTPUT_LIMIT = 4_000
# How much of a long step output to keep from the END. pytest writes the actionable tail LAST —
# the "short test summary info" (`FAILED path::test`) + the `=== N failed, M passed ===` count —
# so a HEAD-only cap silently ate the summary, starving parse_failing_count (→ None → the
# honest-stop's progress breaker never engaged, #56). Keep head (early failure diffs, #55) AND
# tail (the summary) so BOTH the coder and the count signal survive truncation.
_STEP_OUTPUT_TAIL = 2_000


def cap_output(text: str, limit: int = _STEP_OUTPUT_LIMIT, tail: int = _STEP_OUTPUT_TAIL) -> str:
    """Truncate output keeping the HEAD and the TAIL (never head-only): the failure context is
    near the top, the pytest summary + count are at the very bottom.

    Public because the agent prompts bound tool output with the same rule — a head-only clip
    would cut off the very line that says what failed."""
    if len(text) <= limit:
        return text
    # Clamp the tail to the budget. Unclamped, any limit < tail makes `dropped` negative and
    # returns MORE text than came in — a "cap" that both fails to cap and reports a negative
    # truncation. Unreachable from today's call sites, but `limit` is a public parameter.
    tail = min(tail, limit)
    head = max(0, limit - tail)
    dropped = len(text) - head - tail
    return f"{text[:head]}\n... (truncated {dropped} chars) ...\n{text[-tail:]}"


# The static-site checker, shipped as a `python -c` program so nothing is
# ever written into the workspace (writes would pollute the run diff) and no
# sandbox-image change is needed. html.parser almost never raises on bad
# input, so the failure conditions are our own: unknown closing tags,
# unclosed non-void/non-auto-closable tags, and missing local assets.
HTML_CHECK_SRC = """
import os, re, sys
from html.parser import HTMLParser

VOID = {"area","base","br","col","embed","hr","img","input","link","meta",
        "param","source","track","wbr"}
AUTO_CLOSE = {"p","li","td","tr","th","tbody","thead","tfoot","dd","dt",
              "option","html","head","body"}
ASSET_TAGS = {"a":"href","link":"href","script":"src","img":"src",
              "source":"src","audio":"src","video":"src","iframe":"src"}
SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")

class Checker(HTMLParser):
    def __init__(self, base_dir):
        super().__init__(convert_charrefs=True)
        self.base_dir = base_dir
        self.stack = []
        self.errors = []
    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)
        want = ASSET_TAGS.get(tag)
        for name, value in attrs:
            if name != want or not value:
                continue
            v = value.strip()
            if not v or v.startswith("#") or v.startswith("//") or SCHEME.match(v):
                continue
            v = v.split("#", 1)[0].split("?", 1)[0]
            if not v:
                continue
            base = "." if v.startswith("/") else self.base_dir
            path = os.path.normpath(os.path.join(base, v.lstrip("/") if v.startswith("/") else v))
            if not os.path.exists(path):
                self.errors.append("missing local asset: " + value)
    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                popped = self.stack.pop()
                if popped not in AUTO_CLOSE:
                    self.errors.append("unclosed <" + popped + ">")
            if self.stack:
                self.stack.pop()
        else:
            self.errors.append("unexpected closing </" + tag + ">")
    def finish(self):
        for tag in self.stack:
            if tag not in AUTO_CLOSE:
                self.errors.append("unclosed <" + tag + ">")

failed = False
checked = 0
for rel in sys.argv[1:]:
    try:
        if os.path.getsize(rel) > 512 * 1024:
            print(rel + ": skipped (file larger than 512KB)")
            continue
        with open(rel, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        print(rel + ": unreadable (" + str(exc) + ")")
        failed = True
        continue
    checker = Checker(os.path.dirname(rel) or ".")
    checker.feed(text)
    checker.close()
    checker.finish()
    checked += 1
    for err in checker.errors:
        print(rel + ": " + err)
        failed = True
print("checked " + str(checked) + " html file(s):", "FAILED" if failed else "OK")
sys.exit(1 if failed else 0)
"""

_MAX_CONFIG_FILES = 50

# Parses each JSON/YAML/TOML data file — real validation for a config/data-only repo
# (json + toml are stdlib; yaml is validated only when a parser is present, otherwise
# honestly noted as skipped). Runs in the sandbox like HTML_CHECK_SRC.
CONFIG_CHECK_SRC = """
import json, sys
try:
    import tomllib
except ImportError:
    tomllib = None
try:
    import yaml
except ImportError:
    yaml = None
bad = []
checked = 0
skipped = []
for p in sys.argv[1:]:
    try:
        raw = open(p, "rb").read().decode("utf-8", "replace")
    except OSError as exc:
        bad.append(p + ": cannot read (" + str(exc) + ")")
        continue
    ext = p.rsplit(".", 1)[-1].lower()
    try:
        if ext == "json":
            json.loads(raw); checked += 1
        elif ext == "toml":
            if tomllib is None:
                skipped.append(p)
            else:
                tomllib.loads(raw); checked += 1
        elif ext in ("yaml", "yml"):
            if yaml is None:
                skipped.append(p)
            else:
                yaml.safe_load(raw); checked += 1
    except Exception as exc:
        bad.append(p + ": " + type(exc).__name__ + ": " + str(exc))
if bad:
    print("INVALID config/data files:")
    for b in bad:
        print("  - " + b)
    sys.exit(1)
note = "; " + str(len(skipped)) + " skipped (no parser in sandbox)" if skipped else ""
print("OK: parsed " + str(checked) + " config/data file(s)" + note)
sys.exit(0)
"""


@dataclass(frozen=True)
class ValidationStep:
    name: str  # "install" | "pytest" | "py-compile" | "html-check" | "custom"
    cmd: list[str]
    timeout: int | None = None  # None → sandbox default
    # An install/setup step runs in the network-ON install phase (run_setup);
    # everything else runs network-off (run).
    network: bool = False
    # When set (relative to cwd), run_plan skips launching this step if the path
    # already exists — the venv stamp, so egress opens at most once per run.
    skip_if_exists: str | None = None


@dataclass(frozen=True)
class ValidationPlan:
    project_type: (
        # custom | python-pytest | python-scripts | static-site | config-data | javascript | unknown
        str
    )
    steps: list[ValidationStep]
    reason: str
    # Optional sandbox image override for THIS plan's steps (None → the run's default image).
    # A LanguagePack whose toolchain isn't the default image (e.g. a Node image for TS) sets it
    # so its install/test steps run on the right toolchain; ``run_plan`` passes it per step
    # (each step is a fresh container, so no sandbox recreation is needed).
    image: str | None = None
    # What a PASS of this plan is actually WORTH (ADR-0034). The pack that builds the plan
    # is the only thing that knows, so it declares it here rather than the gate guessing
    # from `project_type`:
    #   "suite"   a real test suite executes (pytest, `npm test`, an operator --test-cmd).
    #   "shallow" it only proves the code parses (compileall, a JSON/TOML parse, an HTML
    #             well-formedness check, a typecheck with no tests).
    #   "none"    nothing is executed.
    # Default "unknown" is deny-by-default: the autonomous reviewer-silence backstop
    # requires "suite", so a pack that forgets to declare parks instead of shipping.
    strength: str = "unknown"
    # Which LanguagePack built this plan, so the engine can ask THAT pack to interpret the run's
    # output into a structured TestReport (#81). A NAME, not the pack object or a callable: this
    # plan is serialized into RunState via as_dict() and LangGraph checkpoints must stay JSON-safe,
    # so the registry is looked up by name at interpretation time. Empty for the operator's
    # `custom` --test-cmd plan, which has no owning pack.
    pack_name: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_type": self.project_type,
            "reason": self.reason,
            "strength": self.strength,
            "pack_name": self.pack_name,
            "steps": [
                {"name": s.name, "cmd": list(s.cmd), "network": s.network} for s in self.steps
            ],
        }


@dataclass(frozen=True)
class ValidationOutcome:
    passed: bool | None
    output: str
    step_results: list[dict[str, Any]] = field(default_factory=list)


def _read_root(workspace: Workspace, name: str) -> str:
    path = workspace.root / name
    try:
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[:_MAX_MANIFEST_READ]
    except OSError:
        return ""


def build_html_step(html_files: list[str]) -> tuple[ValidationStep, str]:
    """``(step, note)`` for the static HTML well-formedness + local-asset check. Shared by the
    ``static-site`` and ``python-scripts``+HTML plans; runs ``HTML_CHECK_SRC`` as a ``python -c``
    program (nothing is written into the workspace). Language-neutral result."""
    checked = html_files[:_MAX_HTML_FILES]
    truncated = len(html_files) > _MAX_HTML_FILES
    count = f"first {_MAX_HTML_FILES} of {len(html_files)}" if truncated else str(len(html_files))
    step = ValidationStep("html-check", [sys.executable, "-c", HTML_CHECK_SRC, *checked], 60)
    return step, f"{count} HTML page(s)"


def build_config_step(data_files: list[str]) -> tuple[ValidationStep, int]:
    """``(step, count)`` for the JSON/YAML/TOML parse check (``config-data`` projects)."""
    checked = data_files[:_MAX_CONFIG_FILES]
    step = ValidationStep("config-parse", [sys.executable, "-c", CONFIG_CHECK_SRC, *checked], 60)
    return step, len(checked)


def detect_validation_plan(
    workspace: Workspace, *, install: bool = True, install_timeout: int | None = None
) -> ValidationPlan:
    """Detect the project's language and build its deterministic validation plan.

    Delegates to the ``LanguagePack`` registry (``mosaera_core.languages``): each pack returns
    a confidence-scored plan or defers, and the strongest signal wins (a pytest config or a
    ``package.json`` beats a stray source file). Adding a language = adding a pack there; this
    function, ``resolve_plan``, ``run_plan`` and the dataclasses stay language-agnostic.

    When ``install`` is set, a suite that declares dependencies gets a leading network-ON
    install step (its tests then run in the resulting environment). Every plan's ``reason`` is
    user-visible honesty — including plans that conclude no offline validation is possible.
    """
    # Lazy import breaks the import cycle: languages/ imports this module's primitives at load.
    from mosaera_core.languages import dispatch

    return dispatch(workspace, install=install, install_timeout=install_timeout)


def resolve_plan(
    workspace: Workspace,
    test_cmd: Sequence[str] | None,
    *,
    install: bool = True,
    install_timeout: int | None = None,
) -> ValidationPlan:
    """An explicit test command always wins; otherwise detect."""
    if test_cmd:
        return ValidationPlan(
            "custom",
            [ValidationStep("custom", list(test_cmd))],
            "user-specified test command",
            # The operator named the command that decides this run. Treat their judgement as
            # a suite — they asserted what "validated" means here (ADR-0034).
            strength="suite",
        )
    return detect_validation_plan(workspace, install=install, install_timeout=install_timeout)


def killing_signal(exit_code: int, timed_out: bool) -> int | None:
    """The signal number that killed a step, or ``None`` if it exited on its own terms.

    A process killed by signal N reports ``128 + N``: 137 is SIGKILL (the container hitting its
    ``--memory`` / ``--pids-limit`` cap), 143 is SIGTERM. **This is not a test result.** No runner
    we drive produces these codes — pytest exits 0-5, unittest 0-1 — so the range is unambiguous.

    Measured live 2026-08-23 (LedgerCLI F77): the test step was SIGKILLed at exit 137 with 69
    passing dots and no failures in the captured output, ``run_plan`` reported it as failing tests,
    and the coder burned 3 iterations / ~794k tokens repairing code that was passing. A producer
    cannot fix an OOM, so routing an infrastructure kill into the fix loop is unwinnable by
    construction — the run has to park for a human instead.

    A timeout is excluded: it has its own honest reporting path and is already special-cased.
    """
    if timed_out or not 129 <= exit_code <= 192:
        return None
    return exit_code - 128


def run_plan(
    plan: ValidationPlan,
    sandbox: SandboxWorker,
    cwd: Any | None = None,
    on_step: Callable[[str, str, str], None] | None = None,
) -> ValidationOutcome:
    """Run every step (complete evidence beats early exit) and aggregate.

    ``network`` steps (dependency install) go through ``sandbox.run_setup`` (the
    network-ON phase); everything else through ``sandbox.run`` (network-off). An
    install step whose ``skip_if_exists`` stamp is already present on the mount
    is skipped, so egress opens at most once per manifest state per run.

    ``on_step(phase, name, detail)`` is an optional progress sink called with ``phase`` in
    ``{"start", "done"}`` around each step. Validation is the one stretch of a run that makes NO
    model calls, so the token counter sits flat and — with nothing emitted until the last step
    finished — a healthy install+suite cycle was indistinguishable from a hung run for minutes at a
    time (owner, 2026-08-23: *"I thought it was stalled"*). Advisory only: a raising sink is
    swallowed, because telemetry must never fail a validation.
    """
    if not plan.steps:
        return ValidationOutcome(None, f"[no validation available]\n{plan.reason}")
    sections: list[str] = []
    step_results: list[dict[str, Any]] = []
    all_ok = True
    killed: str = ""

    def _note(phase: str, name: str, detail: str) -> None:
        if on_step is None:
            return
        try:
            on_step(phase, name, detail)
        except Exception:  # noqa: S110 — a progress sink must never fail a validation
            pass

    for step in plan.steps:
        if step.skip_if_exists and cwd is not None and (Path(cwd) / step.skip_if_exists).exists():
            sections.append(f"[step {step.name}: skipped — {step.skip_if_exists} already present]")
            step_results.append(
                {
                    "name": step.name,
                    "exit_code": 0,
                    "timed_out": False,
                    "ok": True,
                    "skipped": True,
                    "duration_s": 0.0,
                    "output": "",
                }
            )
            continue
        runner = sandbox.run_setup if step.network else sandbox.run
        kwargs: dict[str, Any] = {"cwd": cwd}
        if step.timeout is not None:
            kwargs["timeout"] = step.timeout
        # Pass the per-plan image ONLY when set, so default (Python) plans call run() with the
        # exact same signature as before — byte-identical behaviour + unaffected test fakes.
        if plan.image is not None:
            kwargs["image"] = plan.image
        # The step's own ceiling, not the sandbox default: `default_timeout` is a DockerSandbox
        # detail, absent from the `SandboxWorker` ABC and from every test fake.
        _note("start", step.name, f"up to {step.timeout}s" if step.timeout else "")
        result = runner(step.cmd, **kwargs)
        signal_no = killing_signal(result.exit_code, result.timed_out)
        if result.timed_out:
            status = "TIMED OUT"
        elif signal_no is not None:
            # Named, not a bare "exit code 137" — the transcript has to say that the environment
            # killed this, or the next reader repeats the diagnosis this cost us.
            status = f"KILLED by signal {signal_no} (exit code {result.exit_code})"
            killed = killed or f"{step.name}: {status}"
        else:
            status = f"exit code {result.exit_code}"
        _note("done", step.name, status)
        # Head+tail cap (not head-only): keep the failure context AND pytest's trailing summary,
        # so parse_failing_count (the honest-stop's convergence signal, #56) can read the count.
        output = cap_output(result.combined_output(limit=10**9))
        sections.append(f"[step {step.name}: {status}]\n{output}")
        step_results.append(
            {
                "name": step.name,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "ok": result.ok,
                "duration_s": result.duration_s,
                "output": output,
            }
        )
        all_ok = all_ok and result.ok
    if killed:
        # `None` = no honest validation available, which the delivery gate reads as
        # `validation_unavailable` and parks for a human (`policies/standards.py`). The distinction
        # this preserves is the whole point: the suite did not fail, it never got to finish, and
        # `False` would send the coder to fix a defect that is not in the code.
        sections.append(f"[validation unavailable — {killed}]")
        return ValidationOutcome(None, "\n\n".join(sections), step_results)
    return ValidationOutcome(all_ok, "\n\n".join(sections), step_results)
