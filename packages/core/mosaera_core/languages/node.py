"""NodePack — the TS/JS LanguagePack (Node CLIs + libraries).

Builds an OFFLINE validation plan for a ``package.json`` project: install deps (network-on
install phase) → typecheck (``tsc --noEmit`` when a ``tsconfig.json`` is present) → run the
test suite (network-off). Runs on a Node-bearing sandbox image
(``infra/docker/sandbox-node.Dockerfile``); the per-plan image override (Stage 1a) selects it.

Scope: Node CLIs + libraries. A running web-app UI can't be validated offline (no browser
runtime in the sandbox), so it is out of scope — a TS library/CLI's oracle is typecheck + the
test suite. A behaviour-smoke (``node <bin> --help``) is deferred: like the Python case, a
hand-rolled CLI would false-fail ``--help``, and typecheck already catches "won't even load".
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from mosaera_core.languages.base import CONFIDENCE_MANIFEST, DetectContext
from mosaera_core.progress import generic_test_report
from mosaera_core.testreport import TestReport
from mosaera_core.validation import (
    ValidationOutcome,
    ValidationPlan,
    ValidationStep,
    _read_root,
)

if TYPE_CHECKING:
    from mosaera_core.tools.repo import Workspace

# The sandbox image carrying the Node toolchain (Node + npm + corepack). Built from
# infra/docker/sandbox-node.Dockerfile. A Node plan runs its steps on this image via the
# per-command image override (ValidationPlan.image, Stage 1a); Python plans keep the default.
NODE_SANDBOX_IMAGE = "mosaera-sandbox-node:dev"

# npm-init's placeholder test script — treat as "no test script", not a real suite.
_NO_TEST_PLACEHOLDER = "no test specified"

# The container root is read-only; npm's cache must go to the writable /tmp tmpfs.
_NPM_CACHE_ENV = "npm_config_cache=/tmp/.npm-cache"

# Per-TEST summary lines, matched in this order (#81). Each runner also prints a per-FILE line
# ("Test Suites:", "Test Files") which must NOT be counted — summing both is the double-count bug
# this replaces. Anchored on the runner's own label so the file line cannot match by accident.
#   vitest:  "      Tests  3 failed | 5 passed (8)"      (also "Tests  8 passed (8)")
#   jest:    "Tests:       3 failed, 5 passed, 8 total"
#   mocha:   "  5 passing (12ms)" / "  3 failing"
_VITEST_TESTS = re.compile(
    r"^\s*Tests\s+(?:(?P<failed>\d+)\s+failed\s*\|\s*)?(?P<passed>\d+)\s+passed", re.MULTILINE
)
_JEST_TESTS = re.compile(
    r"^\s*Tests:\s+(?:(?P<failed>\d+)\s+failed,\s*)?(?P<passed>\d+)\s+passed", re.MULTILINE
)
_MOCHA = re.compile(
    r"^\s*(?P<passed>\d+)\s+passing\b(?:.*?^\s*(?P<failed>\d+)\s+failing\b)?",
    re.MULTILINE | re.DOTALL,
)


def _parse_package_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _install_step(ws: Workspace, timeout: int | None) -> ValidationStep:
    """Install deps into ``node_modules`` on the ``/work`` mount (network-on install phase),
    stamped by lockfile hash so egress opens at most once per lockfile state. Package manager
    chosen by lockfile — ``npm ci`` / ``pnpm`` / ``yarn`` frozen when a lockfile is present,
    else ``npm install``. Caches go to the writable ``/tmp`` (read-only container root)."""
    lock_pnpm = _read_root(ws, "pnpm-lock.yaml")
    lock_yarn = _read_root(ws, "yarn.lock")
    lock_npm = _read_root(ws, "package-lock.json")
    if lock_pnpm:
        cmd = "pnpm install --frozen-lockfile --store-dir /tmp/.pnpm-store"
        manifest = lock_pnpm
    elif lock_yarn:
        cmd = "yarn install --frozen-lockfile --cache-folder /tmp/.yarn-cache"
        manifest = lock_yarn
    elif lock_npm:
        cmd = f"{_NPM_CACHE_ENV} npm ci --no-audit --no-fund"
        manifest = lock_npm
    else:
        cmd = f"{_NPM_CACHE_ENV} npm install --no-audit --no-fund"
        manifest = _read_root(ws, "package.json")
    h = hashlib.sha256(manifest.encode("utf-8", "replace")).hexdigest()[:12]
    stamp = f"node_modules/.mosaera-stamp-{h}"
    # `mkdir -p node_modules` before the stamp: a zero-dependency `npm install` (e.g. a CLI
    # with only a `start`/`test` script — MCB-23's own reference is dependency-free) reports
    # "up to date" and never creates node_modules/, so a bare `touch node_modules/.stamp`
    # would fail with ENOENT and sink the whole install step. Found by the H-9 e2e test.
    script = f"test -f {stamp} || ({cmd} && mkdir -p node_modules && touch {stamp})"
    return ValidationStep(
        "install", ["sh", "-c", script], timeout=timeout, network=True, skip_if_exists=stamp
    )


def _test_step(pkg: dict[str, Any]) -> tuple[ValidationStep, str] | None:
    """The network-off test step: honour the project's ``test`` script when it's a real one,
    else fall back to a known runner found in (dev)dependencies. ``None`` when no test suite is
    detectable (the plan then relies on the typecheck floor)."""
    scripts = pkg.get("scripts")
    test_script = scripts.get("test", "") if isinstance(scripts, dict) else ""
    if test_script and _NO_TEST_PLACEHOLDER not in test_script:
        step = ValidationStep("test", ["sh", "-c", f"{_NPM_CACHE_ENV} npm test --silent"])
        return step, "npm test"
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    for runner, invocation in (
        ("vitest", "npx --no-install vitest run"),
        ("jest", "npx --no-install jest"),
        ("mocha", "npx --no-install mocha"),
    ):
        if runner in deps:
            return ValidationStep(
                "test", ["sh", "-c", f"{_NPM_CACHE_ENV} {invocation}"]
            ), invocation
    return None


class NodePack:
    name = "node"

    def interpret(self, outcome: ValidationOutcome) -> TestReport | None:
        """Read the JS runner's own summary (#81) — fixing a measured wrong count.

        Node did not merely lack a parser; it had a WRONG one. ``parse_failing_count`` sums every
        ``N failed`` match in the output, and every major JS runner prints TWO such lines — one
        per-file and one per-test::

            jest:   "Test Suites: 1 failed, 1 total" + "Tests: 3 failed, 5 passed"  -> 4, not 3
            vitest: "Test Files  1 failed (1)"       + "Tests  3 failed | 5 passed" -> 4, not 3
            mocha:  "3 failing"                                                      -> None

        A wrong count is worse than none: it feeds ``bump_progress``'s best-so-far tracker, so a
        run that genuinely went 4→3 could read as 5→4 and a converging run could be scored as
        stagnant. Mocha's shape matched nothing at all, so it silently took the no-count path.

        Two deliberate conservatisms:

        * only the ``test`` STEP's output is read. If install or typecheck failed first, the suite
          never ran — that is no-signal, not "zero failures".
        * an UNRECOGNISED summary falls back to the generic parser, so a runner this does not know
          is exactly as good (or bad) as it was before, never newly blind.
        """
        step = next((s for s in outcome.step_results if s.get("name") == "test"), None)
        if step is None:
            # The suite never ran (install/typecheck failed, or this plan is typecheck-only).
            return None
        text = str(step.get("output") or "")
        for pattern in (_VITEST_TESTS, _JEST_TESTS, _MOCHA):
            found = list(pattern.finditer(text))
            if not found:
                continue
            # RED-TEAM R1 (ADR-0077): a test file can PRINT anything, including a line shaped
            # like its runner's summary. The real summary is emitted LAST, after the suite has
            # run, so take the final match rather than the first.
            groups = found[-1].groupdict()
            failed = int(groups.get("failed") or 0)
            passed = int(groups["passed"]) if groups.get("passed") else None
            return TestReport(
                failed=failed,
                passed=passed,
                total=(failed + passed) if passed is not None else None,
            )
        return generic_test_report(text)

    def detect(self, ctx: DetectContext) -> tuple[int, ValidationPlan] | None:
        ws = ctx.workspace
        if not (ws.root / "package.json").is_file():
            return None
        pkg = _parse_package_json(_read_root(ws, "package.json"))
        steps: list[ValidationStep] = []
        labels: list[str] = []
        if ctx.install:
            steps.append(_install_step(ws, ctx.install_timeout))
            labels.append("install deps")
        if (ws.root / "tsconfig.json").is_file():
            steps.append(ValidationStep("typecheck", ["sh", "-c", "npx --no-install tsc --noEmit"]))
            labels.append("tsc --noEmit")
        test = _test_step(pkg)
        if test is not None:
            step, label = test
            steps.append(step)
            labels.append(label)
        # Nothing beyond install proves correctness → honest "unavailable" (empty steps park).
        if not any(s.name in ("typecheck", "test") for s in steps):
            return CONFIDENCE_MANIFEST, ValidationPlan(
                "node",
                [],
                "Node project (package.json) with no tsconfig and no test suite — no offline "
                "correctness check available.",
                image=NODE_SANDBOX_IMAGE,
                strength="none",
            )
        reason = "Node/TS project (package.json): " + ", ".join(labels)
        # A `test` script actually executes a suite; a lone `tsc --noEmit` only proves the
        # code typechecks, which is a parse-class check — not evidence of behaviour (ADR-0034).
        strength = "suite" if test is not None else "shallow"
        return CONFIDENCE_MANIFEST, ValidationPlan(
            "node", steps, reason, image=NODE_SANDBOX_IMAGE, strength=strength
        )
