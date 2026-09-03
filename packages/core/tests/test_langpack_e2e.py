"""End-to-end: the Node and SQL LanguagePacks actually validate on their real images.

Docker-gated AND image-gated (skipped without a daemon or without the per-language image
built — GitHub CI builds only the Python image, GitLab builds all four). Runs the FULL
validation path — ``detect_validation_plan`` / ``resolve_plan`` → ``run_plan`` — against a
real ``DockerSandbox`` on the language image, proving:

- NodePack: ``npm install`` (egress) then the test suite runs network-off on
  ``mosaera-sandbox-node:dev``; a failing suite is reported as failed (not a silent exit-0).
- SqlPack: the ``initdb → pg_ctl → psql`` bootstrap boots an ephemeral Postgres and applies
  schema + assertion queries under ``--network none --read-only --cap-drop ALL`` as a
  non-root user on ``mosaera-sandbox-sql:dev``.

This is the H-9 regression net the shape-only unit tests could never provide: before this,
NOTHING executed either image. Uses the built-in ``node:test`` runner (no third-party test
deps) so the node cases don't depend on registry reachability for anything but a trivial
``npm install``.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from mosaera_core.bench.grade import GraderOutcome, grade
from mosaera_core.languages.node import NODE_SANDBOX_IMAGE
from mosaera_core.languages.sql import SQL_SANDBOX_IMAGE, SqlPack
from mosaera_core.sandbox import DockerSandbox
from mosaera_core.tools.repo import Workspace
from mosaera_core.validation import detect_validation_plan, resolve_plan, run_plan

_DOCKER_BIN = os.environ.get("MOSAERA_DOCKER_BIN", "docker")
_SANDBOX_USER = os.environ.get("MOSAERA_SANDBOX_USER", "sandbox")
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Infrastructure absence goes through the repo-root gate (#58): it reports the
# reason and ERRORS rather than skips when MOSAERA_INTEGRATION=required.
requires_node_image = pytest.mark.requires_docker(NODE_SANDBOX_IMAGE)
requires_sql_image = pytest.mark.requires_docker(SQL_SANDBOX_IMAGE)
# ...but running as root is a BY-DESIGN incompatibility, not a missing precondition,
# so it stays a skip even under `required`: Postgres refuses to initdb as root, and
# the hardened --cap-drop ALL container cannot drop privileges (no CAP_SETUID /
# CAP_CHOWN), so SqlPack needs a non-root sandbox — the production default, which CI
# deliberately overrides with MOSAERA_SANDBOX_USER=root.
skip_sql_as_root = pytest.mark.skipif(
    _SANDBOX_USER == "root",
    reason="the sandbox runs as root; SqlPack requires a non-root sandbox (by design)",
)


def _mountable_workdir() -> Path:
    # docker.exe (WSL) can only bind-mount Windows-filesystem paths; native Linux mounts anywhere.
    if _DOCKER_BIN.lower().endswith(".exe"):
        base = _REPO_ROOT / ".mosaera" / "_pytest_langpack_e2e"
    else:
        base = Path(os.environ.get("TMPDIR", "/tmp")) / "mosaera_langpack_e2e"  # noqa: S108
    d = base / uuid.uuid4().hex[:12]
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def workdir() -> Iterator[Path]:
    d = _mountable_workdir()
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _write(workdir: Path, files: dict[str, str]) -> Workspace:
    for rel, content in files.items():
        p = workdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return Workspace(root=workdir, run_id="e2e", branch="b")


def _node_sandbox(workdir: Path) -> DockerSandbox:
    return DockerSandbox(
        workdir,
        image=NODE_SANDBOX_IMAGE,
        docker_bin=_DOCKER_BIN,
        default_timeout=180,
        install_network="bridge",  # the install phase needs egress for `npm install`
        user=_SANDBOX_USER,
    )


def _sql_sandbox(workdir: Path) -> DockerSandbox:
    # No install_network needed: the sql-validate step is network-off (embedded Postgres).
    return DockerSandbox(
        workdir,
        image=SQL_SANDBOX_IMAGE,
        docker_bin=_DOCKER_BIN,
        default_timeout=180,
        user=_SANDBOX_USER,
    )


# A dependency-free Node package whose suite uses the built-in `node --test` runner, so the
# test never depends on a registry package (npm install fetches nothing). This also exercises
# the zero-dependency install path — the one the H-9 e2e caught NodePack failing on.
_PKG_JSON_PASS = '{"name": "e2e-node", "version": "1.0.0", "scripts": {"test": "node --test"}}\n'
_SRC_JS = "function add(a, b) {\n  return a + b;\n}\nmodule.exports = { add };\n"
_TEST_JS_PASS = (
    "const test = require('node:test');\n"
    "const assert = require('node:assert');\n"
    "const { add } = require('../src/add.js');\n"
    "test('add', () => { assert.strictEqual(add(2, 3), 5); });\n"
)
_TEST_JS_FAIL = (
    "const test = require('node:test');\n"
    "const assert = require('node:assert');\n"
    "const { add } = require('../src/add.js');\n"
    "test('add is wrong', () => { assert.strictEqual(add(2, 3), 99); });\n"
)


@requires_node_image
def test_nodepack_runs_a_passing_suite_on_the_real_image(workdir: Path) -> None:
    ws = _write(
        workdir,
        {"package.json": _PKG_JSON_PASS, "src/add.js": _SRC_JS, "test/add.test.js": _TEST_JS_PASS},
    )
    plan = resolve_plan(ws, None, install=True, install_timeout=300)
    assert plan.project_type == "node"
    assert plan.image == NODE_SANDBOX_IMAGE
    assert [s.name for s in plan.steps] == ["install", "test"]
    assert (
        plan.strength == "suite"
    )  # a real test script → strong enough for the backstop (ADR-0034)

    outcome = run_plan(plan, _node_sandbox(workdir), cwd=workdir)
    assert outcome.passed is True, outcome.output


@requires_node_image
def test_nodepack_reports_a_failing_suite_as_failed(workdir: Path) -> None:
    # Proves the pack RUNS the suite (not just exits 0): a wrong assertion must fail the run.
    ws = _write(
        workdir,
        {"package.json": _PKG_JSON_PASS, "src/add.js": _SRC_JS, "test/add.test.js": _TEST_JS_FAIL},
    )
    plan = resolve_plan(ws, None, install=True, install_timeout=300)
    outcome = run_plan(plan, _node_sandbox(workdir), cwd=workdir)
    assert outcome.passed is False, outcome.output


# A small constrained schema + a passing assertion query (and a failing one for the negative test).
_SCHEMA_SQL = (
    "CREATE TABLE book (\n"
    "  id serial PRIMARY KEY,\n"
    "  isbn text NOT NULL UNIQUE,\n"
    "  price numeric NOT NULL CHECK (price > 0)\n"
    ");\n"
)
_ASSERT_OK_SQL = (
    "INSERT INTO book (isbn, price) VALUES ('111', 9.99);\n"
    "DO $$ BEGIN\n"
    "  IF (SELECT count(*) FROM book) <> 1 THEN RAISE EXCEPTION 'expected 1 row'; END IF;\n"
    "END $$;\n"
)
# A query that must trip a constraint — the CHECK (price > 0) rejects a zero price.
_ASSERT_FAIL_SQL = "INSERT INTO book (isbn, price) VALUES ('222', 0);\n"


@requires_sql_image
@skip_sql_as_root
def test_sqlpack_applies_schema_and_passes_assertions_on_the_real_image(workdir: Path) -> None:
    ws = _write(workdir, {"schema.sql": _SCHEMA_SQL, "tests/assert.sql": _ASSERT_OK_SQL})
    plan = detect_validation_plan(ws)
    assert plan.project_type == "sql"
    assert plan.image == SQL_SANDBOX_IMAGE
    assert [s.name for s in plan.steps] == ["sql-validate"]
    assert plan.steps[0].network is False  # embedded Postgres, no egress
    assert plan.strength == "suite"  # assertion queries in tests/ ARE the suite (ADR-0034)

    outcome = run_plan(plan, _sql_sandbox(workdir), cwd=workdir)
    assert outcome.passed is True, outcome.output
    assert "[sql-validate] OK" in outcome.output
    # #81: the run must also be COUNTABLE, not merely green — that count is what lets the
    # convergence breaker conclude honestly instead of fingerprint-parking a SQL run as thrash.
    report = SqlPack().interpret(outcome)
    assert report is not None, outcome.output
    assert (report.failing, report.passed) == (0, 1)


@requires_sql_image
@skip_sql_as_root
def test_sqlpack_reports_a_failing_assertion_as_failed(workdir: Path) -> None:
    # A CHECK-violating insert makes psql (ON_ERROR_STOP=1) exit non-zero → the run fails.
    ws = _write(workdir, {"schema.sql": _SCHEMA_SQL, "tests/assert.sql": _ASSERT_FAIL_SQL})
    plan = detect_validation_plan(ws)
    outcome = run_plan(plan, _sql_sandbox(workdir), cwd=workdir)
    assert outcome.passed is False, outcome.output
    assert "[sql-validate] OK" not in outcome.output
    report = SqlPack().interpret(outcome)
    assert report is not None and report.failing == 1, outcome.output
    assert list(report.failing_ids) == ["tests/assert.sql"]


@requires_sql_image
@skip_sql_as_root
def test_sqlpack_counts_a_mixed_pass_fail_suite(workdir: Path) -> None:
    # The case the OLD bootstrap could not express at all: it aborted on the first failing
    # assertion (`set -e`), so "1 of 2 failing" and "2 of 2 failing" looked identical and the
    # coder had no way to see itself converging. Now each assertion runs and the tally reports.
    ws = _write(
        workdir,
        {
            "schema.sql": _SCHEMA_SQL,
            "tests/a_ok.sql": _ASSERT_OK_SQL,
            "tests/b_bad.sql": _ASSERT_FAIL_SQL,
        },
    )
    outcome = run_plan(detect_validation_plan(ws), _sql_sandbox(workdir), cwd=workdir)
    assert outcome.passed is False, outcome.output
    report = SqlPack().interpret(outcome)
    assert report is not None, outcome.output
    assert (report.passed, report.failed, report.total) == (1, 1, 2), outcome.output
    assert list(report.failing_ids) == ["tests/b_bad.sql"]


@requires_sql_image
@skip_sql_as_root
def test_sqlpack_schema_error_reports_no_countable_result(workdir: Path) -> None:
    # A schema that will not apply is NOT "one failing assertion" — nothing ran. interpret must
    # say "no signal" so the best-so-far tracker is never seeded with an incommensurable 1.
    ws = _write(workdir, {"schema.sql": "CREATE TABLE (((;\n", "tests/a.sql": _ASSERT_OK_SQL})
    outcome = run_plan(detect_validation_plan(ws), _sql_sandbox(workdir), cwd=workdir)
    assert outcome.passed is False, outcome.output
    assert "schema-error" in outcome.output, outcome.output
    assert SqlPack().interpret(outcome) is None


# --- MCB-26 grader soundness IN THE SANDBOX ------------------------------------------
# The host-side grader-soundness net (test_bench_cases.py) proves MCB-23 winnable via host
# `node`, but SKIPS the SQL case ("sql" is not host-gradeable — it needs a live Postgres). So
# MCB-26's grader/reference pair had NO deterministic machine proof — the exact gap the audit
# flagged ("never machine-verified as winnable; a manual read, not a gate"). These two close
# it by running MCB-26's REAL grader through the real `grade()` path in the sql sandbox — no
# model, fully deterministic.
_MCB26 = Path(__file__).resolve().parents[1] / "mosaera_core" / "bench" / "cases" / "MCB-26"


def _grade_mcb26(workdir: Path, *, solved: bool) -> GraderOutcome:
    if solved:  # overlay the reference solution (schema.sql) onto the bare greenfield tree
        for p in (_MCB26 / "reference").rglob("*"):
            if p.is_file():
                dst = workdir / p.relative_to(_MCB26 / "reference")
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(p.read_bytes())
    ws = Workspace(root=workdir, run_id="e2e", branch="b")
    return grade(ws, _MCB26 / "grader", _sql_sandbox(workdir), kind="sql")


@requires_sql_image
@skip_sql_as_root
def test_mcb26_grader_passes_on_its_reference(workdir: Path) -> None:
    # Winnable: the reference schema.sql satisfies every hidden grader assertion.
    outcome = _grade_mcb26(workdir, solved=True)
    assert outcome.ran, outcome.output
    assert outcome.failed == 0 and outcome.passed > 0, outcome.output


@requires_sql_image
@skip_sql_as_root
def test_mcb26_grader_fails_on_the_bare_state(workdir: Path) -> None:
    # Not trivially satisfied: with no schema delivered, the assertions can't pass — a
    # do-nothing run cannot score Implementation=100.
    outcome = _grade_mcb26(workdir, solved=False)
    assert outcome.failed > 0, outcome.output
