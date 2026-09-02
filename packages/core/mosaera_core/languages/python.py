"""PythonPack — the Python LanguagePack (pytest suites + bare-script projects).

Extracted verbatim from the historical ``detect_validation_plan`` Python branches plus the
Python-only helpers (install step, behaviour-smoke, entrypoint sniff). Behaviour-preserving:
``test_validation.py`` (incl. the false-park regression corpus) is the guard.
"""

from __future__ import annotations

import hashlib
import sys
from typing import TYPE_CHECKING

from mosaera_core.languages.base import (
    CONFIDENCE_SOURCES,
    CONFIDENCE_SUITE,
    DetectContext,
)
from mosaera_core.progress import generic_test_report
from mosaera_core.testreport import TestReport
from mosaera_core.validation import (
    ValidationOutcome,
    ValidationPlan,
    ValidationStep,
    _read_root,
    build_html_step,
)

if TYPE_CHECKING:
    from mosaera_core.tools.repo import Workspace

# Entrypoint filenames tried first when sniffing for a runnable CLI (most-likely first).
_ENTRY_NAMES = ("__main__.py", "cli.py", "main.py", "app.py", "run.py", "manage.py")

# CLI frameworks whose ``--help`` exits 0 (argparse/click/typer print help and return cleanly),
# making ``--help`` a safe "does it start" probe. A hand-rolled ``sys.argv`` dispatcher does not
# implement ``--help`` (it's an unknown command → non-zero exit), so smoking ``--help`` against
# one would false-fail correct code — the reason the behaviour-smoke gate must guard on this.
_HELP_FRAMEWORKS = ("argparse", "click", "typer")


def _implements_help(src: str) -> bool:
    """True when the entrypoint IMPORTS a CLI framework whose ``--help`` exits 0.

    Checks for an actual ``import``/``from`` statement — not a bare substring — so a comment
    or docstring that merely *mentions* one of these words (e.g. a hand-rolled CLI noting
    "intentionally not using argparse") can't re-enable the ``--help`` smoke and false-fail
    correct code."""
    return any(f"import {fw}" in src or f"from {fw}" in src for fw in _HELP_FRAMEWORKS)


def _declares_installable_package(pyproject: str, setup_cfg: str) -> bool:
    """True when the manifests actually declare an INSTALLABLE package — i.e. build
    metadata, not just tool config. A ``pyproject.toml`` carrying only ``[tool.*]`` sections
    (pytest/ruff/mypy config) is NOT installable: ``pip install -e .`` on it fails, which
    would false-fail a correct, fully-tested deliverable."""
    return "[build-system]" in pyproject or "[project]" in pyproject or "[metadata]" in setup_cfg


def _install_step(workspace: Workspace, timeout: int | None) -> tuple[ValidationStep, str] | None:
    """A pip-install step for a python project that declares dependencies, or None when it
    declares none (a zero-dep suite runs on the base image's pytest, unchanged). Deps go into
    ``/work/.venv`` on the writable mount so they persist from the network-ON install container
    into the network-off test container. A manifest-content hash stamps the venv so install is a
    no-op once warm."""
    req = _read_root(workspace, "requirements.txt")
    pyproject = _read_root(workspace, "pyproject.toml")
    setup_cfg = _read_root(workspace, "setup.cfg")
    has_setup_py = (workspace.root / "setup.py").is_file()
    if req:
        args, manifest, label = "-r requirements.txt", req, "requirements.txt"
    elif has_setup_py or _declares_installable_package(pyproject, setup_cfg):
        args, manifest, label = "-e .", pyproject or setup_cfg or "setup.py", "the project package"
    else:
        # A pyproject/setup.cfg that carries ONLY tool config (no package metadata) is not
        # installable — skip install; a zero-dep suite runs on the base image's pytest.
        return None
    h = hashlib.sha256(manifest.encode("utf-8", "replace")).hexdigest()[:12]
    stamp = f".venv/.stamp-{h}"
    # Single atomic idempotent shell: (re)create the venv + install only when the manifest-hash
    # stamp is absent. Relative paths → cwd is the workspace root. --system-site-packages layers
    # the repo's deps ON TOP of the base image, so the venv's python still sees the image's
    # pinned pytest (which is not installed into a bare venv).
    # --copies (not the default symlink): the venv lives on the /work mount, shared with the
    # Windows host. A symlinked `.venv/bin/python → /usr/local/bin/python` is a DANGLING symlink
    # on the host (that target is the container's), so any host-side stat of it raises
    # `OSError [WinError 1920]` and crashes the run. Copying the interpreter makes it a plain file
    # that stats cleanly cross-platform — the root-cause fix for the bench crash (#56).
    script = (
        f"test -f {stamp} || "
        f"(python -m venv --copies --system-site-packages .venv && "
        f".venv/bin/pip install {args} && touch {stamp})"
    )
    step = ValidationStep(
        "install", ["sh", "-c", script], timeout=timeout, network=True, skip_if_exists=stamp
    )
    return step, label


def project_interpreter(workspace: Workspace) -> str:
    """The interpreter this project's own code is importable from RIGHT NOW.

    ``_pytest_plan`` names `.venv/bin/python` because it has just QUEUED the install step that
    creates it — it knows what WILL exist. A probe has to ask the other question: what DOES exist,
    this instant, in a container that can install nothing (no network, read-only `/work`).
    Conflating the two would aim a fresh clone's first probe at a venv that is not there yet.

    Returns the RELATIVE path, spelled as `_pytest_plan` spells it, because every sandbox call runs
    with ``cwd=workspace.root``. `--copies` in ``_install_step`` is what makes the host-side check
    trustworthy: the interpreter is a real file rather than a dangling container symlink, so an
    absent or unusable venv fails ``is_file()`` and falls back — the safe direction.

    F87: ``sandbox_exec`` hardcoded ``sys.executable``, so for any ``pip install -e .`` project the
    coder's probes could not import the package while validation's pytest could. One live run spent
    291,846 coder tokens diagnosing that as "network issues installing dependencies"; the code was
    correct and the suite passed. Same defect and same fix as ADR-0049's B3 false-park.
    """
    venv_python = workspace.root / ".venv" / "bin" / "python"
    return ".venv/bin/python" if venv_python.is_file() else sys.executable


def _behaviour_smoke_step(
    workspace: Workspace, listing: list[str], interp: str
) -> tuple[ValidationStep, str] | None:
    """A deterministic BEHAVIOUR floor: actually START the deliverable's entrypoint, so a
    package/CLI that passes its unit tests but can't even run (import error, syntax error at
    import, broken argparse wiring) is caught (ADR-0025). Returns a network-OFF ``--help`` smoke
    step, or None when no framework CLI entrypoint is confidently detected (conservative: never
    false-fail a fine deliverable). Only entrypoints using argparse/click/typer are smoked; a
    hand-rolled ``sys.argv`` CLI gets no ``--help`` floor (its behaviour is the tester's job)."""
    # A package with a __main__ module — run it as a module, but only when its entrypoint
    # actually implements --help (else --help is an "unknown command" → non-zero → false fail).
    pkg_mains = [e for e in listing if e.endswith("/__main__.py") and e.count("/") == 1]
    if pkg_mains:
        pkg = pkg_mains[0].split("/", 1)[0]
        if _implements_help(_read_root(workspace, pkg_mains[0])):
            return ValidationStep(
                "cli-smoke", [interp, "-m", pkg, "--help"], 30
            ), f"python -m {pkg}"
        return None
    # A top-level CLI script — run the file directly (cwd is the workspace root).
    top_py = [e for e in listing if e.endswith(".py") and "/" not in e]
    ordered = sorted(top_py, key=lambda f: (_ENTRY_NAMES.index(f) if f in _ENTRY_NAMES else 99, f))
    for f in ordered:
        src = _read_root(workspace, f)
        if 'if __name__ == "__main__"' in src and _implements_help(src):
            return ValidationStep("cli-smoke", [interp, f, "--help"], 30), f
    return None


class PythonPack:
    """Python: a pytest suite (strong signal) or bare Python sources (weak signal)."""

    name = "python"

    def interpret(self, outcome: ValidationOutcome) -> TestReport | None:
        """pytest's summary IS the shape ``generic_test_report`` reads, so this delegates (#81).

        Deliberately reads the AGGREGATE ``outcome.output`` rather than isolating the pytest
        step's own output: the pre-#81 code parsed the aggregate too, so routing through here is a
        LITERAL no-op for every Python run. Narrowing to the pytest step would be a behaviour
        change (an install-phase line containing "1 error" currently counts) and needs its own
        evidence — it is not smuggled into the refactor that makes the signal structured.
        """
        return generic_test_report(outcome.output)

    def detect(self, ctx: DetectContext) -> tuple[int, ValidationPlan] | None:
        ws, listing = ctx.workspace, ctx.listing
        basenames = [entry.rsplit("/", 1)[-1] for entry in listing]
        has_pytest_config = (
            (ws.root / "pytest.ini").is_file()
            or "[tool.pytest" in _read_root(ws, "pyproject.toml")
            or "[tool:pytest]" in _read_root(ws, "setup.cfg")
            or "[pytest]" in _read_root(ws, "tox.ini")
        )
        test_files = [
            b
            for b in basenames
            if b.endswith(".py") and (b.startswith("test_") or b.endswith("_test.py"))
        ]
        html_files = sorted(e for e in listing if e.endswith((".html", ".htm")))

        if has_pytest_config or test_files:
            return CONFIDENCE_SUITE, self._pytest_plan(ctx, has_pytest_config, test_files)
        if any(entry.endswith(".py") for entry in listing):
            return CONFIDENCE_SOURCES, self._scripts_plan(ctx, html_files)
        return None

    def _pytest_plan(
        self, ctx: DetectContext, has_pytest_config: bool, test_files: list[str]
    ) -> ValidationPlan:
        ws, listing = ctx.workspace, ctx.listing
        evidence = "pytest configuration" if has_pytest_config else f"test files ({test_files[0]}…)"
        steps: list[ValidationStep] = []
        interp = sys.executable
        reason = f"pytest detected ({evidence})"
        install_step = _install_step(ws, ctx.install_timeout) if ctx.install else None
        if install_step is not None:
            step, label = install_step
            steps.append(step)
            interp = ".venv/bin/python"  # run pytest inside the installed venv
            reason += f"; installing {label} into .venv first (network on for install only)"
        elif ctx.install:
            reason += "; no dependency manifest — running on the sandbox's pytest"
        else:
            reason += "; dependency install disabled — deps not installed"
        # Whole-suite validation (#45, ADR-0054): run pytest's OWN config-driven discovery from the
        # workspace root — NO hard-coded `tests/` scope and NO synthesized path args. The old
        # `pytest tests` skipped every test outside tests/, so a root-level regression shipped
        # green. Bare `pytest -q` discovers the whole tree (tests/, root, any dir) while HONORING
        # the repo's own `testpaths`/`python_files`/`norecursedirs` and pytest's defaults that skip
        # `.venv`/`node_modules`/`build`/… — which synthesizing explicit CLI paths would OVERRIDE
        # (red-team ADR-0054: CLI paths defeat `testpaths` → false-park on committed examples/vendor
        # tests, read a 300-capped listing, and collide on duplicate basenames). `--import-mode=
        # importlib` gives each test file a path-unique module name so same-basename files across
        # dirs (`tests/test_utils.py` + a root `test_utils.py`) don't clash under prepend mode. Also
        # fixes the old fixtures-only-tests/ false-fail for free (root tests are found).
        # `-o verbosity_assertions=2` (#55, ADR-0059): keep `-q`'s quiet whole-suite summary, but
        # show the FULL expected-vs-actual on a FAILING assertion. Plain `-q` truncates a long diff
        # ("Full output truncated, use -vv"), so the coder can't see e.g. a single-space format
        # mismatch and flails; this restores the exact diff without the noise of a full `-vv` run,
        # at zero extra cost (no re-run). Passing tests still print as `.`.
        # `--ignore=.mosaera` prunes the agent SCRATCH space (#59, ADR-0064) from collection. It is
        # ADDITIVE (unlike `-o norecursedirs=…`, which would REPLACE the repo's config, forbidden by
        # ADR-0054), so a scratch `test_*.py` can never be collected — even if the untrusted repo
        # overrides `norecursedirs` and drops pytest's default `.*` prune (#59 red-team). Belt with
        # the git + _SKIP_DIRS suspenders: scratch is invisible to delivery/grading/tamper/runs.
        pytest_args = [
            interp, "-m", "pytest", "-q", "-o", "verbosity_assertions=2",
            "--import-mode=importlib", "--ignore=.mosaera",
        ]  # fmt: skip
        reason += "; whole suite (config-driven)"
        steps.append(ValidationStep("pytest", pytest_args))
        smoke = _behaviour_smoke_step(ws, listing, interp)
        if smoke is not None:
            step, label = smoke
            steps.append(step)
            reason += f"; behaviour smoke: {label} --help"
        # A real pytest suite executes → strong enough to carry an autonomous delivery
        # over a silent reviewer (ADR-0034).
        return ValidationPlan("python-pytest", steps, reason, strength="suite")

    def _scripts_plan(self, ctx: DetectContext, html_files: list[str]) -> ValidationPlan:
        ws, listing = ctx.workspace, ctx.listing
        steps = [
            ValidationStep(
                "py-compile",
                [
                    sys.executable,
                    "-m",
                    "compileall",
                    "-q",
                    "-x",
                    r"[\\/](\.git|node_modules|\.venv)[\\/]",
                    ".",
                ],
                120,
            )
        ]
        reason = "Python sources without a test suite — syntax check only (python -m compileall)"
        if html_files:
            step, note = build_html_step(html_files)
            steps.append(step)
            reason += f"; plus checks on {note}"
        smoke = _behaviour_smoke_step(ws, listing, sys.executable)
        if smoke is not None:
            step, label = smoke
            steps.append(step)
            reason += f"; behaviour smoke: {label} --help"
        # compileall proves the code PARSES, nothing more. The ADR-0025 behaviour-smoke
        # (`--help`) is a floor, not a suite — it proves the entrypoint starts, not that it
        # is correct. So a green run here is "shallow": it may still deliver on a reviewer
        # APPROVE, but it may NOT ride the reviewer-silence backstop (ADR-0034).
        return ValidationPlan("python-scripts", steps, reason, strength="shallow")
