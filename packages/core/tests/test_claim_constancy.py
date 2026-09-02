"""The behavioural claim reason carries NO per-claim information, and materiality cannot leak.

Both pins come from the #84 investigation
(`docs/engineering-history/claim-constancy-2026-08-08.md`). ADR-0090 measured that 19 of 23 MCB
cases emit a byte-identical failed-claim id set on every run and deferred the cause; the cause is
that `acceptance_test`, `validation_exit` and `wellformedness_parse` all resolve to
`state["tests_passed"]` verbatim, so a case's behavioural ids fail together or not at all.

**These are not tautology tests.** The first fails the moment a behavioural kind acquires a genuine
per-claim oracle — exactly when ADR-0090 MR2's premise ("this reason restates `validation_failed`")
stops holding, and precisely when we would want to be told. A tripwire on an argument, not a
description of code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mosaera_core.claim_oracles import evaluate_claims, failed_claim_ids
from mosaera_core.claims import claims_as_dicts, claims_from_acceptance

# The three kinds whose oracle is `state["tests_passed"]` verbatim (claim_oracles.evaluate_claims).
_BEHAVIOURAL = frozenset({"acceptance_test", "validation_exit", "wellformedness_parse"})

_CASES = Path(__file__).resolve().parents[1] / "mosaera_core" / "bench" / "cases"


def _brief_claims(case: str) -> list[dict[str, Any]]:
    return claims_as_dicts(claims_from_acceptance(None, (_CASES / case / "brief.md").read_text()))


def test_behavioural_claims_carry_no_per_claim_information() -> None:
    """Every behavioural claim of a case fails together, or none does.

    This is the whole of ADR-0090 MR2's premise, pinned. `unsatisfied_claim` on a behavioural-only
    case is `validation_failed` restated once per claim: the reason tells an operator nothing the
    validation result did not already say, and the ids identify no specific unmet requirement.

    Uses a REAL brief rather than a fixture, so the pin describes the corpus the benchmark actually
    measures rather than a shape invented here.
    """
    claims = _brief_claims("MCB-01")
    behavioural = [c["id"] for c in claims if c["oracle_kind"] in _BEHAVIOURAL]
    assert behavioural, "MCB-01 mints no behavioural claims — the fixture drifted, not the code"

    failed = failed_claim_ids(evaluate_claims(claims, None, {"tests_passed": False}))
    assert sorted(failed) == sorted(behavioural), (
        "the failed set is no longer exactly the behavioural id list — a behavioural kind has "
        "gained a per-claim oracle. That is GOOD, and it invalidates ADR-0090 MR2's premise that "
        "this reason merely restates validation_failed. Re-read #84 before changing this test."
    )

    passing = failed_claim_ids(evaluate_claims(claims, None, {"tests_passed": True}))
    assert passing == [], "a behavioural claim failed on a passing suite"

    unknown = failed_claim_ids(evaluate_claims(claims, None, {"tests_passed": None}))
    assert unknown == [], "no validator ran, so nothing is proven failed — that is `unevaluable`"


def test_the_pin_would_notice_a_per_claim_oracle() -> None:
    """Prove the tripwire fires, so it cannot pass by vacuity.

    A guard asserted only against today's behaviour is untested for the case it exists to catch —
    green-by-vacancy, this repo's own recorded defect class. Here a behavioural kind is given a
    verdict that varies per claim, and the property above must break.
    """
    claims = _brief_claims("MCB-01")
    behavioural = [c["id"] for c in claims if c["oracle_kind"] in _BEHAVIOURAL]

    rows = evaluate_claims(claims, None, {"tests_passed": False})
    # Simulate one behavioural claim acquiring a real oracle that says it IS satisfied.
    for row in rows:
        if row["claim_id"] == behavioural[0]:
            row["verdict"] = "satisfied"
    assert sorted(failed_claim_ids(rows)) != sorted(behavioural)


def test_every_material_claim_the_corpus_mints_is_bound_and_every_bound_one_is_material() -> None:
    """Materiality cannot leak into the gate — pinned, not left to coincidence.

    `failed_claim_ids` does not filter on `material` and `evaluate_claims` never reads it. An
    immaterial claim can only fail to reach the gate because every `material=False` return site in
    `classify_sentence` happens to pair with `kind="none"` — an invariant enforced nowhere. Measured
    across all 24 briefs it holds with zero violations, so pinning it is inert today and closes the
    hole before something relies on it.
    """
    offenders: list[tuple[str, str, str]] = []
    briefs = sorted(p for p in _CASES.glob("*/brief.md"))
    assert briefs, "no MCB briefs found — the corpus moved"
    for brief in briefs:
        for claim in claims_from_acceptance(None, brief.read_text()):
            if not claim.material and claim.oracle_kind != "none":
                offenders.append((brief.parent.name, claim.id, claim.oracle_kind))
    assert not offenders, (
        f"immaterial claims carrying a BOUND oracle_kind: {offenders} — these can reach the gate "
        "as `unsatisfied_claim` because failed_claim_ids does not filter on `material`. Either "
        "classify_sentence must keep immaterial ⇒ kind 'none', or the gate path must filter."
    )


def test_an_immaterial_claim_with_a_bound_kind_would_reach_the_gate() -> None:
    """The hole the test above guards, demonstrated — so the guard's necessity is evidence.

    If this ever stops holding (i.e. the gate path starts filtering on materiality) the test above
    becomes belt-and-braces rather than the only thing standing between an immaterial sentence and
    a park. Worth knowing either way.
    """
    smuggled = [
        {
            "id": "x-c1",
            "text": "should feel fast",
            "oracle_kind": "acceptance_test",
            "material": False,
        }
    ]
    failed = failed_claim_ids(evaluate_claims(smuggled, None, {"tests_passed": False}))
    assert failed == ["x-c1"], (
        "the gate path now filters immaterial claims — good; relax the corpus guard above to "
        "belt-and-braces and record it"
    )
