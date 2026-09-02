"""SqlPack — the SQL LanguagePack (schema + migrations against embedded Postgres).

Validates a SQL project OFFLINE by booting an EPHEMERAL Postgres **inside the test container**
(data dir + socket on the writable ``/tmp`` tmpfs — no networked sidecar, so ``--network none``
and the read-only root are preserved), applying the schema/migrations, then running any
assertion queries. Proven feasible by the sandbox spike (initdb → pg_ctl → psql all run under
``--network none --read-only --cap-drop ALL`` as a non-root user).

Oracle: the schema/migrations must apply cleanly (valid SQL, FKs/types resolve) and every
assertion query must succeed. An assertion ``tests/*.sql`` file signals failure by RAISE-ing
(``ON_ERROR_STOP`` makes psql exit non-zero) — that convention is the tester's job (see the
LanguagePack SOP / ADR-0032). Runs on a Postgres-bearing sandbox image; web/ORM tooling is out
of scope for this first cut.

**Requires a NON-ROOT sandbox** (uid 1000 `sandbox`, the production default): Postgres refuses
to `initdb`/run as root, and the hardened container (`--cap-drop ALL --security-opt
no-new-privileges`) strips `CAP_SETUID`/`CAP_CHOWN`, so a *root* container can neither run the
engine nor drop to a non-root user — SQL validation is unavailable there. The default sandbox
user is non-root; only a root-configured sandbox (e.g. the CI `sandbox-e2e` job, which owns its
bind mount as root) is affected, and the executed e2e tests skip on it accordingly.
"""

from __future__ import annotations

import re

from mosaera_core.languages.base import CONFIDENCE_SOURCES, DetectContext
from mosaera_core.testreport import TestReport
from mosaera_core.validation import ValidationOutcome, ValidationPlan, ValidationStep

# The tally SQL_BOOTSTRAP emits, and the per-file failure marker beside it.
#
# RED-TEAM R1 (ADR-0077): the workspace is UNTRUSTED and its `tests/*.sql` output is echoed
# into this text, so a repo can print a line that looks like the tally. Two mitigations, both
# needed: anchor at LINE START (psql indents result rows, so a forged SELECT output cannot sit
# flush-left) and take the LAST match (the bootstrap always prints the real tally last, after
# every assertion has run). Bounded even unmitigated — no count reaches the gate, and
# tests_passed comes from exit codes — but a forged descending trend could burn iterations.
_TALLY = re.compile(r"^\[sql-validate\]\s+(\d+) passed,\s+(\d+) failed", re.MULTILINE)
_FAILED_FILE = re.compile(r"^FAILED:\s+(\S+)", re.MULTILINE)

# The sandbox image carrying Postgres (initdb/pg_ctl/psql) + a non-root sandbox user. Built from
# infra/docker/sandbox-sql.Dockerfile; selected via the per-command image override (Stage 1a).
SQL_SANDBOX_IMAGE = "mosaera-sandbox-sql:dev"

# Boot an ephemeral local Postgres, apply schema/migrations, run assertion tests — all network-off
# (the DB is a unix socket in /tmp; nothing leaves the container). Writes only to /tmp (tmpfs) so
# the read-only container root is respected. `set -e` + ON_ERROR_STOP make any SQL error fail hard.
SQL_BOOTSTRAP = r"""set -e
export PGDATA=/tmp/pgdata
initdb -D "$PGDATA" -U app --auth=trust -N >/dev/null
pg_ctl -D "$PGDATA" -o "-c unix_socket_directories=/tmp" -w -t 60 start >/dev/null
createdb -h /tmp -U app app
run() { psql -h /tmp -U app -d app -v ON_ERROR_STOP=1 -q -f "$1"; }
# Apply schema / migrations — first present source wins (ordered migrations, else a single
# schema.sql, else any top-level *.sql sorted).
if ls migrations/*.sql >/dev/null 2>&1; then FILES=$(ls migrations/*.sql | sort)
elif [ -f schema.sql ]; then FILES=schema.sql
else FILES=$(ls *.sql 2>/dev/null | sort); fi
# detect() matches *.sql anywhere; the applier only knows migrations/, schema.sql, *.sql. If a
# SQL repo keeps its schema elsewhere (e.g. db/schema.sql) FILES is empty — fail honestly with a
# fix-it message rather than "apply nothing" then falsely report OK.
if [ -z "$FILES" ]; then
  echo "[sql-validate] no schema/migrations found (looked in migrations/, schema.sql, ./*.sql)" >&2
  exit 1
fi
# Applying the schema is ALL-OR-NOTHING: if the DDL won't load there is no database to assert
# against, so this aborts with a distinct marker. SqlPack.interpret keys on that marker to report
# "no countable result" rather than "1 failure" — a schema error and a count of failed assertions
# are different units, and conflating them corrupts the best-so-far convergence tracker (#81).
for f in $FILES; do
  echo "[apply] $f"
  if ! run "$f"; then echo "[sql-validate] schema-error: $f" >&2; exit 1; fi
done
# Assertion queries (optional): each raises (exit non-zero) on a failed check. Run them
# INDIVIDUALLY and tally, rather than aborting on the first — a count is what the convergence
# breaker needs to tell "12 failing → 3 failing" from "spinning" (#81). Same shape bench/grade.py
# already emits for its SQL grader. psql's own error text is left on stderr so the coder still
# sees WHY each one failed.
pass=0; fail=0
if ls tests/*.sql >/dev/null 2>&1; then
  for f in $(ls tests/*.sql | sort); do
    echo "[test] $f"
    if run "$f"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAILED: $f"; fi
  done
  echo "[sql-validate] $pass passed, $fail failed"
fi
if [ "$fail" -gt 0 ]; then exit 1; fi
echo "[sql-validate] OK"
"""


class SqlPack:
    name = "sql"

    def interpret(self, outcome: ValidationOutcome) -> TestReport | None:
        """Read the ``[sql-validate] N passed, M failed`` tally this pack's bootstrap emits (#81).

        Returns ``None`` — no countable result — in two cases, and the first is the subtle one:

        * **schema-error.** The schema/migrations did not apply, so no assertion ever ran. Reporting
          that as ``failed=1`` would be a category error: it would seed the best-so-far tracker with
          ``best=1``, which then permanently out-ranks a genuinely better later state of "3 failing
          assertions against a schema that now loads" — and the run would false-trip as
          non-converging exactly when it had started converging.
        * **no assertions.** A schema-only project (``strength="shallow"``) has nothing to count.

        Both are honest no-signal answers, routed by the no-count path rather than faked into a
        number.
        """
        text = outcome.output or ""
        if "[sql-validate] schema-error" in text:
            return None
        matches = _TALLY.findall(text)
        if not matches:
            return None
        passed, failed = int(matches[-1][0]), int(matches[-1][1])  # LAST = the real tally
        ids = tuple(_FAILED_FILE.findall(text))[:5]  # display cap; NOT a security-relevant set
        return TestReport(failed=failed, total=passed + failed, passed=passed, failing_ids=ids)

    def detect(self, ctx: DetectContext) -> tuple[int, ValidationPlan] | None:
        sql_files = [e for e in ctx.listing if e.endswith(".sql")]
        # Require a schema/migration source, not ONLY assertion tests — a bare tests/*.sql with
        # nothing to apply isn't a SQL project we can validate.
        if not any(not e.startswith("tests/") for e in sql_files):
            return None
        step = ValidationStep("sql-validate", ["sh", "-c", SQL_BOOTSTRAP], 120)
        has_asserts = any(e.startswith("tests/") for e in sql_files)
        reason = "SQL project (schema/migrations): apply to an ephemeral in-container Postgres" + (
            ", then run assertion queries" if has_asserts else ""
        )
        # Assertion queries in tests/ ARE the suite. Applying the schema alone proves the DDL
        # is valid against a real engine — real evidence, but about syntax, not behaviour, so
        # it must not carry an autonomous delivery over a silent reviewer (ADR-0034).
        strength = "suite" if has_asserts else "shallow"
        return CONFIDENCE_SOURCES, ValidationPlan(
            "sql", [step], reason, image=SQL_SANDBOX_IMAGE, strength=strength
        )
