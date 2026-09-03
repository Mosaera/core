"""Grade a delivered benchmark run against its hidden acceptance suite.

The suite is injected into the delivered workspace at grade time only (never
during the run — it would pollute the diff and be auto-detected as the run's own
validation), then executed in the hardened sandbox. The pass/fail counts are the
Implementation ground truth.

Language-aware: the grader runs on the deliverable's toolchain image and speaks
its idiom — pytest for Python (base image), a self-contained node driver for
Node/TS (``mosaera-sandbox-node``), psql assertions against an ephemeral Postgres
for SQL (``mosaera-sandbox-sql``). All three emit the same ``N passed, N failed``
summary, so one parser covers every language. The image is selected per grade via
``ValidationPlan.image`` (Stage 1a) — the run itself already picks it the same way.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from mosaera_core.languages.node import NODE_SANDBOX_IMAGE
from mosaera_core.languages.sql import SQL_SANDBOX_IMAGE
from mosaera_core.sandbox import SandboxWorker
from mosaera_core.tools.repo import Workspace
from mosaera_core.validation import ValidationPlan, ValidationStep, run_plan

# The hidden suite's directory inside a graded workspace. Public because `layer2.py` must PURGE
# it before any Layer-2 step runs — a second copy of this string is how the two would drift.
GRADER_DIR = "_mcb_grader"
_GRADER_DIR = GRADER_DIR
_SUMMARY = {
    "passed": re.compile(r"(\d+) passed"),
    "failed": re.compile(r"(\d+) failed"),
    "errors": re.compile(r"(\d+) errors?"),
}
# Failing test ids from pytest's short summary (`FAILED path::name - ...`, `ERROR path::name`)
# and from the shell driver above (`FAILED: <name>`), so every grader kind names its failures.
# `collecting` is excluded deliberately: pytest writes `ERROR collecting <path>` for an import
# failure, and the naive pattern captured the word "collecting" as the test id — which is exactly
# what happened on MCB-18, the one run in the 2026-08-05 sweep whose diagnostic mattered. The path
# is the second token there, so it is captured instead.
_FAILED_ID = re.compile(r"(?:FAILED|ERROR)(?::\s+|\s+)(?:collecting\s+)?(\S+)")

# The Node grader is a self-contained driver (built-in node only — no dep on the
# delivered package's test framework) that exercises the deliverable and prints the
# shared "N passed, N failed" summary.
_NODE_GRADE_ARGV = ["node", f"{_GRADER_DIR}/run.mjs"]

# The SQL grader boots an ephemeral Postgres (like SqlPack's SQL_BOOTSTRAP), applies
# the DELIVERED schema/migrations, then runs each hidden assertion `_mcb_grader/*.sql`
# as its own psql (ON_ERROR_STOP → a RAISE/failed check exits non-zero), tallying to
# the shared summary. Network-off, /tmp tmpfs — same containment as the SqlPack run.
_SQL_GRADE = r"""set -e
export PGDATA=/tmp/pgdata
initdb -D "$PGDATA" -U app --auth=trust -N >/dev/null
pg_ctl -D "$PGDATA" -o "-c unix_socket_directories=/tmp" -w -t 60 start >/dev/null
createdb -h /tmp -U app app
apply() { psql -h /tmp -U app -d app -v ON_ERROR_STOP=1 -q -f "$1"; }
if ls migrations/*.sql >/dev/null 2>&1; then FILES=$(ls migrations/*.sql | sort)
elif [ -f schema.sql ]; then FILES=schema.sql
else FILES=$(ls *.sql 2>/dev/null | sort); fi
for f in $FILES; do apply "$f"; done
pass=0; fail=0
for g in $(ls _mcb_grader/*.sql | sort); do
  if psql -h /tmp -U app -d app -v ON_ERROR_STOP=1 -q -f "$g" >/dev/null 2>&1; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1)); echo "FAILED: $g"
  fi
done
echo "$pass passed, $fail failed"
"""


@dataclass(frozen=True)
class GraderOutcome:
    ran: bool
    passed: int
    failed: int
    errors: int
    output: str

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors

    @property
    def all_passed(self) -> bool:
        return self.ran and self.total > 0 and self.failed == 0 and self.errors == 0

    @property
    def failed_test_ids(self) -> list[str]:
        """The names of the tests that failed/errored, for the scorecard.

        The counts alone cannot be reconciled with the delivered tree after the fact — the
        whole point of keeping this is that "7/8" tells you nothing about WHICH assertion the
        ground truth rejected. Best-effort by construction: an unparseable output yields an
        empty list, never an exception, because a diagnostic must not break a measurement.
        """
        return _FAILED_ID.findall(self.output or "")


def _parse(output: str) -> tuple[int, int, int]:
    def find(key: str) -> int:
        m = _SUMMARY[key].search(output)
        return int(m.group(1)) if m else 0

    return find("passed"), find("failed"), find("errors")


def _grade_step(kind: str, timeout: int) -> tuple[str | None, ValidationStep]:
    """The ``(image, step)`` for the deliverable's language: which toolchain image to
    run on (None → the base Python image) and the command that runs the hidden grader
    and emits ``N passed, N failed``."""
    if kind in ("node-cli", "node"):
        return NODE_SANDBOX_IMAGE, ValidationStep("acceptance", _NODE_GRADE_ARGV, timeout=timeout)
    if kind == "sql":
        return SQL_SANDBOX_IMAGE, ValidationStep(
            "acceptance", ["sh", "-c", _SQL_GRADE], timeout=timeout
        )
    # Python (and any static/other kind whose grader is pytest): the base image.
    return None, ValidationStep(
        "acceptance",
        # `--tb=line -rf`: one line per failure plus the failure summary. The old `--tb=no`
        # discarded the assertion text, which is precisely the thing needed to reconcile a
        # recorded score against the delivered tree. Pass/fail semantics are unchanged.
        ["python", "-m", "pytest", "-q", "--tb=line", "-rf", "-p", "no:cacheprovider", _GRADER_DIR],
        timeout=timeout,
    )


def grade(
    workspace: Workspace,
    grader_dir: Path,
    sandbox: SandboxWorker,
    *,
    kind: str = "python-cli",
    timeout: int = 300,
) -> GraderOutcome:
    """Inject the hidden suite into ``workspace`` and run it on the deliverable's
    toolchain image (chosen by ``kind``)."""
    dest = workspace.root / _GRADER_DIR
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(grader_dir, dest)

    # Language-aware image+step (this branch) AND strength="suite" (ADR-0034, from main): the
    # hidden grader IS a real executed suite, so a delivered run graded green is trustworthy.
    image, step = _grade_step(kind, timeout)
    plan = ValidationPlan(
        "grade", [step], "MCB hidden acceptance suite", image=image, strength="suite"
    )
    outcome = run_plan(plan, sandbox, cwd=workspace.root)
    if outcome.passed is None:
        return GraderOutcome(ran=False, passed=0, failed=0, errors=0, output=outcome.output)
    passed, failed, errors = _parse(outcome.output)
    return GraderOutcome(
        ran=True, passed=passed, failed=failed, errors=errors, output=outcome.output
    )
