"""The escalation ladder's run loop, and the rule that an escalation must have HAPPENED.

Split out of ``cli.py`` at the 500-line god-file ceiling — the precedent ``_exec.py`` and
``_modify_amendment.py`` set. Cohesive on its own terms: it owns one question the rest of the CLI
does not ask, *did the escalated producer actually speak?*, and the answer decides which attempt is
allowed to be the run's recorded outcome. See ADR-0016 Amendment 1.
"""

from __future__ import annotations

from collections.abc import Callable

from mosaera_core.bench.cases import BenchCase
from mosaera_core.bench.escalation import diagnose_bottleneck, escalate_role
from mosaera_core.bench.grade import GraderOutcome
from mosaera_core.bench.harness import RunOutcome, run_case
from mosaera_core.config import Settings
from mosaera_core.cost import role_calls
from mosaera_core.models import cloud_tier_allowed

# What became of an escalation, recorded on the card. Before this, `escalation_path` said what
# was ATTEMPTED and nothing said whether it RAN — so 45 stored cards carry a no-op attempt that
# reads exactly like a genuine one. "" = none attempted.
ESCALATION_APPLIED = "applied"
ESCALATION_NO_CALLS = "no_calls_discarded"


def run_with_escalation(
    case: BenchCase,
    settings: Settings,
    backend: str,
    run_id: str,
    grade_run: Callable[[RunOutcome, BenchCase, Settings, str], GraderOutcome],
) -> tuple[RunOutcome, GraderOutcome, list[str], str]:
    """Run the case and grade it. A run "succeeds" only when it DELIVERS **and** passes the
    hidden acceptance suite — so both a non-delivery (a park) AND a false-positive ship
    (delivered but the grader fails, e.g. a too-lenient tester) count as a bottleneck. When
    escalation is enabled, deterministically diagnose the culprit role, bump it one tier,
    and re-run — up to ``max_model_escalations``. Returns (run, grader, path, outcome).
    See ADR-0016 (+ its 2026-08-10 amendment, below).

    **The escalated attempt is kept only if the escalated role actually spoke.** Measured
    2026-08-10: 45 of 61 stored escalations produced ZERO calls from the escalated role — every one
    binding `anthropic/claude-sonnet-5` on an unfunded key. Each of those no-ops was returned as
    the run's outcome, overwriting a tier-0 result that had really happened, with `error=None` and
    an `escalation_path` still naming the model. A failed escalation was indistinguishable from
    "a stronger model tried and could not", and reading it the second way inverted the conclusions
    drawn from six runs.

    `cloud_tier_allowed` cannot close this: it checks the model is PRICED (correctly — that is what
    bounds the USD cap), and priced is not funded. Reachability is only knowable after a call, so
    the check is post-hoc and the rule is the conservative one: an attempt in which the producer
    never answered is not evidence about that producer, so it is discarded rather than believed.
    """
    path: list[str] = []
    current = settings
    attempt = 0
    prior: tuple[RunOutcome, GraderOutcome] | None = None
    while True:
        rid = run_id if attempt == 0 else f"{run_id}-esc{attempt}"
        run = run_case(case, current, run_id=rid, sandbox_backend=backend)
        grader = grade_run(run, case, settings, backend)
        if prior is not None and path:
            # The escalated role never spoke → the ladder did not happen. Fall back to the retained
            # tier-0 pair and STOP: a further rung binds the same unreachable provider.
            escalated_role = path[-1].split(":", 1)[0].strip()
            if role_calls(run.rollup, escalated_role) == 0:
                print(
                    f"  escalation had NO EFFECT ({escalated_role} made 0 calls)"
                    " — keeping the tier-0 result"
                )
                return prior[0], prior[1], path, ESCALATION_NO_CALLS
        delivered = bool(run.final.get("approved"))
        if (
            (delivered and grader.all_passed)
            or not settings.model_escalation_enabled
            or attempt >= settings.max_model_escalations
        ):
            return run, grader, path, (ESCALATION_APPLIED if path else "")
        # Delivered but the hidden grader fails → a false-positive ship (grader-informed).
        acceptance_failed = delivered and grader.ran and not grader.all_passed
        role = diagnose_bottleneck(run.final, current, acceptance_failed=acceptance_failed)
        if role is None:
            # nothing attributable — don't escalate blindly
            return run, grader, path, (ESCALATION_APPLIED if path else "")
        esc = escalate_role(current, role)
        if esc is None:
            # the diagnosed role is already at the top tier
            return run, grader, path, (ESCALATION_APPLIED if path else "")
        # Off-box egress gate (ADR-0024), mirroring the live path (_escalation.py:51-61). A CLOUD
        # tier fires only when egress is consented AND the model is priced (so the USD cap bounds
        # it). Otherwise refuse — else the bench binds an unpriced/unreachable cloud tier that
        # no-op's and OVERWRITES the tier-0 outcome with thrash, inflating the scoreboard (#54
        # confound). The bench had no such gate; the live runner already did.
        bump = esc.settings.role_model(esc.role)
        if not cloud_tier_allowed(current, bump.provider, bump.model):
            print(f"  escalation blocked: {esc.role} cloud egress not permitted ({bump.model})")
            return run, grader, path, (ESCALATION_APPLIED if path else "")
        why = "shipped work that fails acceptance" if acceptance_failed else "did not deliver"
        print(f"  escalate: {esc.label}  ({why} — {role} diagnosed)")
        path.append(esc.label)
        prior = (run, grader)
        current = esc.settings
        attempt += 1
