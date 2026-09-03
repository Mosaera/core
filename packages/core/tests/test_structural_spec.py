"""Structural-spec oracle (#80, ADR-0072) — the MCB-05 false_ship class.

A behaviour-preserving refactor can still miss a STATED structural shape (a short orchestrator that
delegates to >= N helpers). These prove the deterministic AST check: extract the asks from the
brief, downgrade a green-but-mis-shaped refactor to False (→ honest_park), leave everything else at
None (deny-by-default, no effect).
"""

from __future__ import annotations

from mosaera_core.structural_spec import (
    check_structural_compliance,
    evaluate_structural_spec,
    extract_structural_constraints,
)

# The real MCB-05 ask (a short orchestrator + >= 3 helpers).
MCB05_BRIEF = """# Refactor the checkout function
**Refactor** `checkout_total` into a short orchestrator that delegates to small, well-named helper
functions.
- `checkout_total` should read as a short orchestrator (a handful of statements) that delegates to
  at least three helper functions in the module.
Keep the public signature `checkout_total(cart, member=False)`.
"""

# The MCB-05 false_ship: behaviour-preserving, 3 helpers, but a 7-statement orchestrator (the
# `if member:` branch left inline) → len(fn.body) == 7 > 6.
DELIVERED_UNMET = '''
def _calculate_subtotal(cart):
    return sum(i["price"] * i["qty"] for i in cart)
def _apply_member_discount(s):
    return s * 0.95
def _calculate_shipping_and_tax(s):
    return (0.0 if s >= 50 else 5.0), s * 0.08
def checkout_total(cart, member=False):
    """Total for cart."""
    if not cart:
        return 0.0
    subtotal = _calculate_subtotal(cart)
    if member:
        subtotal = _apply_member_discount(subtotal)
    shipping, tax = _calculate_shipping_and_tax(subtotal)
    total = round(subtotal + tax + shipping, 2)
    return total
'''

# A compliant refactor: a 4-statement orchestrator delegating to 3 helpers.
DELIVERED_MET = '''
def _line_total(item):
    return item["price"] * item["qty"]
def _subtotal(cart):
    return sum(_line_total(i) for i in cart)
def _member(s, m):
    return s * 0.95 if m else s
def _ship_tax(s):
    return (0.0 if s >= 50 else 5.0) + s * 0.08
def checkout_total(cart, member=False):
    """Total for cart."""
    if not cart:
        return 0.0
    subtotal = _member(_subtotal(cart), member)
    return round(subtotal + _ship_tax(subtotal), 2)
'''


def test_extract_mcb05_brief() -> None:
    c = extract_structural_constraints(MCB05_BRIEF)
    assert c is not None
    assert c.target == "checkout_total"
    assert c.min_helpers == 3
    # ADR-0072 successor: a bare "a handful of statements" no longer resolves to a CONSTANT. The
    # old `_HANDFUL = 6` was provably unsound (MCB-05 and MCB-15 use near-identical wording and
    # both extracted 6, yet their graders score <=6 and <=7). The ask is recorded; the check
    # resolves it against the function's own pre-refactor body.
    assert c.max_body is None
    assert c.wants_shorter is True


# The pre-refactor original: one long function, the shape the brief asks to decompose.
ORIGINAL_MONOLITH = '''
def checkout_total(cart, member=False):
    """Total for cart."""
    if not cart:
        return 0.0
    subtotal = 0.0
    for item in cart:
        subtotal += item["price"] * item["qty"]
    if member:
        subtotal = subtotal * 0.95
    shipping = 0.0 if subtotal >= 50 else 5.0
    tax = subtotal * 0.08
    return round(subtotal + shipping + tax, 2)
'''


def test_unmet_shape_downgrades() -> None:
    # The delivered orchestrator barely shrank against its own pre-refactor self → downgrade.
    verdict, reason = evaluate_structural_spec(
        MCB05_BRIEF, {"checkout.py": DELIVERED_UNMET}, {"checkout.py": ORIGINAL_MONOLITH}
    )
    assert verdict is False  # a stated-but-unmet structural criterion → downgrade → honest_park
    assert "checkout_total" in reason and "where it was" in reason


def test_without_a_baseline_the_relative_check_is_inert() -> None:
    """Deny-by-default: no pre-refactor body → no claim.

    A greenfield task or a brand-new module has nothing to have shrunk FROM. The old absolute
    check would still have judged it against an invented constant; this one abstains.
    """
    verdict, _ = evaluate_structural_spec(MCB05_BRIEF, {"checkout.py": DELIVERED_UNMET})
    assert verdict is not False


def test_compliant_refactor_is_met() -> None:
    # WITH the pre-refactor baseline both halves of the ask are measurable — the shrink AND
    # the helper count — so the shape is genuinely proven and the verdict may vouch.
    verdict, _ = evaluate_structural_spec(
        MCB05_BRIEF, {"checkout.py": DELIVERED_MET}, {"checkout.py": ORIGINAL_MONOLITH}
    )
    assert verdict is True  # short orchestrator + enough helpers → no downgrade


def test_a_partially_measurable_ask_never_vouches() -> None:
    """RED-TEAM R2 — half a check is not proof of the whole shape.

    The brief asks for two things: a short orchestrator AND >= 3 helpers. With no baseline the
    shrink half cannot be measured, and passing the helper count alone used to report "meets the
    requested structure" — a vouch (satisfied -> structural_vouch_ids -> oracle_verified) earned
    by looking at half the ask. Unevaluable instead: no vouch, and no false park either.
    """
    verdict, reason = evaluate_structural_spec(MCB05_BRIEF, {"checkout.py": DELIVERED_MET})
    assert verdict is None, reason
    assert "of 2 structural checks" in reason


def test_no_structural_intent_is_none() -> None:
    assert extract_structural_constraints("Add a CSV export button to the report page.") is None
    verdict, _ = evaluate_structural_spec("Fix the login bug.", {"a.py": DELIVERED_UNMET})
    assert verdict is None  # no constraint in the brief → no effect


def test_refactor_without_a_shape_ask_is_none() -> None:
    # Intent present but no helper/body criterion → nothing to check.
    assert extract_structural_constraints("Refactor `checkout_total` for clarity.") is None


def test_target_not_in_changed_files_is_none() -> None:
    verdict, reason = evaluate_structural_spec(
        MCB05_BRIEF, {"other.py": "def foo():\n    return 1\n"}
    )
    assert verdict is None  # unverifiable (target absent) → deny-by-default, no downgrade
    assert "not found" in reason


def test_min_helpers_unmet_downgrades() -> None:
    brief = "Refactor `f` to delegate to at least three helper functions."
    src = (
        "def _a():\n    return 1\n"
        "def f():\n    x = _a()\n    return x\n"  # delegates to only 1 helper
    )
    verdict, reason = evaluate_structural_spec(brief, {"m.py": src})
    assert verdict is False
    assert "delegates to 1" in reason


def test_explicit_numbers_and_wordforms() -> None:
    c = extract_structural_constraints(
        "Refactor `g` into no more than 4 statements, delegating to 2 helpers."
    )
    assert c is not None and c.max_body == 4 and c.min_helpers == 2


def test_syntax_error_source_is_skipped_not_crashed() -> None:
    verdict, _ = evaluate_structural_spec(MCB05_BRIEF, {"broken.py": "def (:\n"})
    assert verdict is None  # a parse fault degrades to None, never raises


def test_check_directly_no_constraint_is_none() -> None:
    from mosaera_core.structural_spec import StructuralConstraints

    v, _ = check_structural_compliance(
        {"m.py": DELIVERED_MET}, StructuralConstraints(None, None, None)
    )
    assert v is None


def test_absurd_number_does_not_crash() -> None:
    # red-team F1: a >4300-digit count must degrade to no-constraint, never raise ValueError
    # (Python's int-str conversion limit) out of the module's "never raises" contract.
    huge = "9" * 4301
    assert (
        extract_structural_constraints(f"Refactor `f` into no more than {huge} statements.") is None
    )
    v, _ = evaluate_structural_spec(
        f"Refactor `f`; delegate to {huge} helper functions.", {"m.py": "def f():\n    return 1\n"}
    )
    assert v is None


def test_deeply_nested_source_does_not_crash() -> None:
    # red-team F2: a RecursionError from ast.parse must degrade to None, not escape the module.
    import sys

    old = sys.getrecursionlimit()
    sys.setrecursionlimit(1000)
    try:
        v, _ = evaluate_structural_spec(
            "Refactor `f` delegating to at least two helpers.",
            {"m.py": "f = " + "not " * 3000 + "1\n"},
        )
    finally:
        sys.setrecursionlimit(old)
    assert v is None


# --- the ACCEPTED-RESIDUAL ratchet (ADR-0072 amendment, 2026-08-02) -------------------
#
# The structural oracle is ACTIVE in the autonomous posture as a BOUNDED, EXPIRING accept: its
# `max_body` statement count is the check ADR-0072's own red-team called provably unsound, and it
# is what actually converts MCB-05 (the Gate 2 blocker). Shipping it is justified only because the
# blast radius is small and MEASURED. These tests are the ratchet that keeps it that way — if a
# future change widens the heuristic, they fail instead of the residual growing silently.


def test_structural_spec_blast_radius_is_bounded() -> None:
    """Only the briefs that genuinely ask for a SHAPE may extract constraints.

    A brief with no structural ask must yield None (deny-by-default → never downgrades). If this
    count grows, the unsound `max_body` check has started firing on cases nobody measured it on.
    """
    from mosaera_core.bench.cases import available_cases, load_case

    engaged = [
        cid
        for cid in available_cases()
        if extract_structural_constraints(load_case(cid).brief) is not None
    ]
    assert engaged == ["MCB-05", "MCB-15"], (
        f"structural oracle now engages on {engaged}; it was measured on exactly the two refactor "
        "briefs. Widening it re-opens the unsound-`max_body` false-park risk on unmeasured cases "
        "— re-measure before changing this list (ADR-0072 amendment)."
    )


def test_structural_spec_never_false_parks_a_known_correct_reference() -> None:
    """THE safety property behind the accept: 0 false-parks on known-correct code.

    Every bench case that ships a `reference/` is correct BY CONSTRUCTION, so a False verdict on
    one is a provable false-park — the exact cost that held activation.
    """
    from mosaera_core.bench.cases import available_cases, load_case

    parked = []
    for cid in available_cases():
        case = load_case(cid)
        if not case.reference_dir.is_dir():
            continue
        sources = {
            p.relative_to(case.reference_dir).as_posix(): p.read_text(
                encoding="utf-8", errors="replace"
            )
            for p in case.reference_dir.rglob("*.py")
            if p.is_file()
        }
        if not sources:
            continue
        verdict, why = evaluate_structural_spec(case.brief, sources)
        if verdict is False:
            parked.append((cid, why))
    assert parked == [], f"structural oracle false-parks known-correct code: {parked}"


def test_the_relative_measure_replaced_the_unsound_constant() -> None:
    """RETIRED the ADR-0072 risk acceptance — this is the successor's proof.

    Its predecessor, `test_the_unsound_body_check_is_still_the_load_bearing_one`, asserted that
    the provably-unsound `max_body` constant was what actually caught MCB-05, and was written to
    FAIL the moment a sound replacement landed. It has now done its job and been replaced by this.

    The same delivered shape is still caught — but relatively, against its own pre-refactor body,
    so no fixed integer is involved and the MCB-05(<=6)/MCB-15(<=7) contradiction cannot recur.
    """
    brief = (
        "Refactor `f` into a short orchestrator (a handful of statements) that delegates to at "
        "least three helper functions."
    )
    original = "def f(c):\n" + "".join(f"    s{i} = {i}\n" for i in range(7)) + "    return s0\n"
    shaped_but_verbose = (
        "".join(f"def _h{i}(c):\n    return {i}\n\n" for i in range(3))
        + "def f(c):\n"
        + "".join(f"    v{i} = _h{i % 3}(c)\n" for i in range(6))
        + "    return v0\n"
    )
    verdict, why = evaluate_structural_spec(brief, {"m.py": shaped_but_verbose}, {"m.py": original})
    assert verdict is False
    assert "where it was" in why  # rejected RELATIVELY...
    assert "<= 6" not in why and "handful" not in why  # ...never against a guessed constant


def test_a_genuinely_short_orchestrator_passes() -> None:
    # The other half of soundness: the rule must not simply reject everything. A real
    # decomposition — the work moved into helpers — is accepted.
    brief = (
        "Refactor `f` into a short orchestrator (a handful of statements) that delegates to at "
        "least three helper functions."
    )
    original = "def f(c):\n" + "".join(f"    s{i} = {i}\n" for i in range(9)) + "    return s0\n"
    good = (
        "".join(f"def _h{i}(c):\n    return {i}\n\n" for i in range(3))
        + "def f(c):\n    a = _h0(c)\n    b = _h1(a)\n    return _h2(b)\n"
    )
    verdict, _ = evaluate_structural_spec(brief, {"m.py": good}, {"m.py": original})
    assert verdict is True


def test_a_shrunk_orchestrator_that_still_iterates_is_caught() -> None:
    """The constant-free companion rule.

    "Extract into helpers" means the ITERATION moves out — both known-correct references go from
    one loop to zero. An orchestrator that shrank but kept its loop kept the very work it was
    asked to delegate, and no statement count can express that.
    """
    brief = (
        "Refactor `f` into a short orchestrator (a handful of statements) that delegates to at "
        "least three helper functions."
    )
    original = (
        "def f(c):\n    t = 0\n    for i in c:\n        t += i\n"
        + "".join(f"    s{i} = {i}\n" for i in range(6))
        + "    return t\n"
    )
    still_loops = (
        "".join(f"def _h{i}(c):\n    return {i}\n\n" for i in range(3))
        + "def f(c):\n    t = 0\n    for i in c:\n        t += _h0(i)\n    return t\n"
    )
    verdict, why = evaluate_structural_spec(brief, {"m.py": still_loops}, {"m.py": original})
    assert verdict is False
    assert "still iterates" in why


# --- red-team regressions (ADR-0072 successor, 3 rounds) ------------------------------

_RT_BRIEF = (
    "Refactor `f` into a short orchestrator (a handful of statements) that delegates to at "
    "least three helper functions."
)
_RT_HELPERS = "".join(f"def _h{i}(c):\n    return {i}\n\n" for i in range(3))


def _rt_original(n: int) -> dict[str, str]:
    return {
        "m.py": "def f(c):\n" + "".join(f"    s{i} = {i}\n" for i in range(n)) + "    return s0\n"
    }


def test_r1_nesting_cannot_hide_the_statement_count() -> None:
    """RED-TEAM R1 — the dodge that defeated the ORIGINAL absolute check.

    Wrap the work in `if True:` and a top-level count reads ONE statement. ADR-0072's first
    red-team found exactly this ("trivially defeated by one level of nesting"); its disposition
    dropped the body check, so no mitigation was ever written and the relative measure inherited
    the hole. Measured: 11% of the original counted top-level (passes), 111% counted in full.
    """
    nested = (
        _RT_HELPERS
        + "def f(c):\n    if True:\n"
        + "".join(f"        v{i} = _h{i % 3}(c)\n" for i in range(8))
        + "        return v0\n"
    )
    verdict, why = evaluate_structural_spec(_RT_BRIEF, {"m.py": nested}, _rt_original(8))
    assert verdict is False, "nesting must not hide the body"
    assert "where it was" in why


def test_r1_deep_nesting_is_also_caught() -> None:
    deep = (
        _RT_HELPERS
        + "def f(c):\n    if c:\n        for i in c:\n            if i:\n"
        + "".join(f"                v{i} = _h{i % 3}(c)\n" for i in range(6))
        + "    return 0\n"
    )
    verdict, _ = evaluate_structural_spec(_RT_BRIEF, {"m.py": deep}, _rt_original(8))
    assert verdict is False


def test_r3_a_small_original_never_false_parks_a_correct_refactor() -> None:
    """RED-TEAM R3 — the false-park generator, and the harm direction.

    An orchestrator delegating to N helpers needs at least N+1 statements, so a `<= 2/3 of the
    original` bound is UNSATISFIABLE on a small original: a perfectly good 3-statement
    orchestrator was being parked. The floor is DERIVED from the brief's own helper count, not
    guessed, and can only ever make the check more permissive.
    """
    good = _RT_HELPERS + "def f(c):\n    a = _h0(c)\n    b = _h1(a)\n    return _h2(b)\n"
    for n in range(0, 6):
        verdict, why = evaluate_structural_spec(_RT_BRIEF, {"m.py": good}, _rt_original(n))
        assert verdict is not False, f"false park on a {n + 1}-statement original: {why}"


def test_r3_the_floor_does_not_disarm_the_check_on_real_targets() -> None:
    # The other half: once the original is big enough for the ask to be satisfiable, a bad shape
    # is still caught. Otherwise the R3 fix would have quietly disabled the oracle.
    bad = (
        _RT_HELPERS
        + "def f(c):\n"
        + "".join(f"    v{i} = _h{i % 3}(c)\n" for i in range(8))
        + "    return v0\n"
    )
    verdict, _ = evaluate_structural_spec(_RT_BRIEF, {"m.py": bad}, _rt_original(8))
    assert verdict is False


def test_r2_no_baseline_is_inert_not_a_park() -> None:
    """RED-TEAM R2 — baseline evasion, dispositioned ACCEPT (documented).

    Relocating the target to a new module leaves no `HEAD` blob, so the relative check has no
    baseline and goes inert — a bad shape then ships. That is the deny-by-default contract, and
    the alternative (park whenever there is no baseline) would false-park every greenfield task.
    The evasion returns to the pre-oracle baseline; it opens no NEW false-ship channel. Pinned
    here so the behaviour is a recorded decision rather than an accident.
    """
    bad = (
        _RT_HELPERS
        + "def f(c):\n"
        + "".join(f"    v{i} = _h{i % 3}(c)\n" for i in range(8))
        + "    return v0\n"
    )
    assert evaluate_structural_spec(_RT_BRIEF, {"m_new.py": bad}, {})[0] is not False
    assert (
        evaluate_structural_spec(_RT_BRIEF, {"m.py": bad}, {"m.py": "def f(:::\n"})[0] is not False
    )


# --- the vacuous-verdict class (no-vacuous-verdicts pass) -------------------------------
#
# The module docstring promises: "It never ships anything — a `False` can only turn a
# would-be ship into a park, so it can never manufacture a false_ship." These pin the
# branches where a `True` was returned having executed ZERO predicates, which breaks that
# promise in the one direction that matters: a satisfied structural claim VOUCHES
# (satisfied_structural_claim_ids -> structural_vouch_ids -> oracle_verified), so a verdict
# manufactured from nothing becomes independence evidence the gate trusts.


def test_shrink_ask_without_a_baseline_is_unevaluable_not_met() -> None:
    # "short orchestrator", no helper count -> min_helpers None, wants_shorter True.
    c = extract_structural_constraints("Refactor `f` into a short orchestrator")
    assert c is not None and c.wants_shorter and c.min_helpers is None
    # No originals: the pre-refactor body is unknown, so the ratio cannot be evaluated...
    verdict, reason = check_structural_compliance({"m.py": "def f():\n    return 1\n"}, c, {})
    # ...and "I could not check" must never read as "met".
    assert verdict is None, f"zero predicates ran, yet the verdict was {verdict!r}: {reason}"


def test_nothing_to_decompose_is_unevaluable_not_met() -> None:
    # The floor branch: `was * 2/3` is unsatisfiable on a tiny original, so the ratio is
    # skipped. Its own comment says "no claim (deny-by-default)" — the verdict must agree.
    c = extract_structural_constraints("Refactor `f` into a short orchestrator")
    assert c is not None
    verdict, _ = check_structural_compliance(
        {"m.py": "def f():\n    return 1\n"}, c, {"m.py": "def f():\n    return 1\n"}
    )
    assert verdict is None


def test_a_real_shrink_ask_with_a_baseline_still_evaluates() -> None:
    # The fix must not blind the check: with a baseline big enough to decompose, a
    # still-inline orchestrator is UNMET (a real downgrade), not unevaluable.
    c = extract_structural_constraints("Refactor `f` into a short orchestrator")
    assert c is not None
    before = "def f():\n" + "".join(f"    x{i} = {i}\n" for i in range(12)) + "    return 1\n"
    verdict, reason = check_structural_compliance({"m.py": before}, c, {"m.py": before})
    assert verdict is False, reason


def test_a_decoy_definition_cannot_shadow_the_real_target() -> None:
    """RED-TEAM R2 — the verdict must not depend on dict insertion order.

    The check returned on the FIRST changed file defining the target, so a trivially-compliant
    decoy `checkout_total` in one file shadowed the real, still-bloated one in another and
    produced a vouch. Every candidate is judged now: an unmet ask anywhere downgrades, and the
    same inputs in either order give the same answer.
    """
    decoy = "def checkout_total():\n    return _a()\n\n\ndef _a():\n    return 1\n"
    a, _ = evaluate_structural_spec(
        MCB05_BRIEF,
        {"decoy.py": decoy, "checkout.py": DELIVERED_UNMET},
        {"checkout.py": ORIGINAL_MONOLITH},
    )
    b, _ = evaluate_structural_spec(
        MCB05_BRIEF,
        {"checkout.py": DELIVERED_UNMET, "decoy.py": decoy},
        {"checkout.py": ORIGINAL_MONOLITH},
    )
    assert a is False and b is False, f"order-dependent verdict: {a!r} vs {b!r}"


def test_an_ambiguous_target_across_files_never_vouches() -> None:
    """Two changed files both define a compliant target: which one the brief meant is not
    knowable, and this verdict vouches — so it is not earned. No park either."""
    met = (
        "def checkout_total():\n    return _a() + _b() + _c()\n\n\n"
        "def _a():\n    return 1\n\n\ndef _b():\n    return 2\n\n\ndef _c():\n    return 3\n"
    )
    verdict, reason = evaluate_structural_spec(
        MCB05_BRIEF,
        {"one.py": met, "two.py": met},
        {"one.py": ORIGINAL_MONOLITH, "two.py": ORIGINAL_MONOLITH},
    )
    assert verdict is None, reason
    assert "ambiguous target" in reason


def test_a_vouch_can_never_come_from_zero_executed_predicates() -> None:
    """The outcome-level guard on the defect that produced every false ship we ever measured.

    Archaeology, 2026-08-05: the 6.9% `false_ship` on the 2026-08-03 baseline — the number v1.0's
    critical path rested on — was ours. `check_structural_compliance` returned *met* after running
    NO predicate, which minted a structural vouch, cleared `oracle_unverified`, and let the gate
    approve work the hidden grader failed. Five runs, MCB-05 x2 and MCB-15 x3.

    A unit test on the counter already exists. It is not enough on its own, and the reason is the
    lesson: the bug survived because every test asserted on the *inputs* to the verdict rather
    than on the property that matters — a satisfied verdict must be backed by an executed check.
    This asserts that property directly, for every shape that reaches this function.
    """
    from mosaera_core.structural_spec import StructuralConstraints, check_structural_compliance

    # A "short orchestrator" ask with no helper count, no explicit max, and no baseline to
    # measure a shrink against: nothing is measurable, so nothing may be vouched.
    unmeasurable = StructuralConstraints(
        target="f", min_helpers=None, max_body=None, wants_shorter=True
    )
    verdict, reason = check_structural_compliance(
        {"m.py": "def f():\n    a = 1\n    return a\n"}, unmeasurable, originals=None
    )
    assert verdict is not True, f"vouched with nothing executed: {reason}"

    # And with no constraint at all, which is the floor branch whose own comment said
    # "no claim (deny-by-default)" while the code once said met.
    empty = StructuralConstraints(target=None, min_helpers=None, max_body=None, wants_shorter=False)
    assert check_structural_compliance({"m.py": "def f():\n    pass\n"}, empty)[0] is not True
