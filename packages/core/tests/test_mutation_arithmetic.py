"""The mutation oracle can ask a question about arithmetic (F83, #92).

Measured 2026-08-08: Layer 2 declined 15 of 15 attempts across 40 runs, every one on code an
independent grader said was correct. With the reason recorded, 7 of 8 were *"the mutation check was
inconclusive"* — the oracle produced NO mutant, so it had nothing to ask. The delivered fix was one
arithmetic line, and the three operators (return→None, flip a comparison, delete a bare call) cover
none of that shape.

Operator choice is evidence-led, not taste (see the ADR):
- **arithmetic** is one of Offutt's five sufficient operators (TOSEM 1996, 99.5% of full coverage
  retained) and has the second-lowest equivalent-mutant rate of the five — 5% under 6 person-months
  of manual analysis (Yao et al., ICSE 2014), 1% under Trivial Compiler Equivalence (ICSE 2015).
  Google ships it across 10 languages; mutmut, cosmic-ray and MutPy all ship it by default.
- **constant ±1** is not in the sufficient set, but is in the Major set that reaches 73% real-fault
  coupling over 357 real faults (Just et al., FSE 2014). Its measured cost is 57% DUPLICATION — and
  that comes from the six-way cross-product, so we generate exactly one mutant per literal.

Both are single-substitution on purpose. The 4-way arithmetic cross-product (31% duplication) and
the six-way constant variant buy coverage we do not need — we need *availability*, one killable
mutant, not an exhaustive probe.
"""

from __future__ import annotations

from pathlib import Path

from mosaera_core.mutation import _all_mutations, _mutate_source

# The exact delivered fix that produced 7 of the 8 inconclusive declines.
_PAGINATION_FIX = '''
def paginate(items: list, page: int, per_page: int) -> list:
    """Return the ``page``-th slice of ``per_page`` items (1-based)."""
    if page < 1 or per_page < 1:
        return []
    start = (page - 1) * per_page
    return items[start : start + per_page]
'''

_CHANGED_LINE = {6}  # `start = (page - 1) * per_page`


def test_the_reproduced_failure_now_produces_a_mutant() -> None:
    """THE regression. This returned None before F83 — no mutant, no question, decline.

    The changed line holds an arithmetic expression and a numeric literal and nothing else: no
    return, no comparison, no bare call. Every previous operator was inapplicable by construction.
    """
    mutant = _mutate_source(_PAGINATION_FIX, _CHANGED_LINE)
    assert mutant is not None, (
        "the changed arithmetic line still yields no mutant — the oracle cannot ask a question "
        "about it, so Layer 2 declines correct work with 'inconclusive' (F83)"
    )
    assert mutant != _PAGINATION_FIX


def test_the_mutant_actually_changes_behaviour() -> None:
    """A mutant that computes the same answer is an equivalent mutant — unkillable, and in this
    gate a wrongful decline. The literature puts equivalents at 8-25% and proves detection
    undecidable, so this cannot be guaranteed in general; it IS checkable for this case.
    """
    mutant = _mutate_source(_PAGINATION_FIX, _CHANGED_LINE)
    assert mutant is not None
    ns_orig: dict = {}
    ns_mut: dict = {}
    exec(compile(_PAGINATION_FIX, "<orig>", "exec"), ns_orig)  # noqa: S102 - fixture in this file
    exec(compile(mutant, "<mutant>", "exec"), ns_mut)  # noqa: S102 - fixture in this file
    items = [1, 2, 3, 4, 5, 6, 7]
    assert ns_orig["paginate"](items, 1, 3) == [1, 2, 3]
    # "Killable" means a test can tell the difference — a different answer OR an error. Both fail a
    # suite; only silent agreement is equivalence, and that is the case this gate must never meet.
    try:
        mutated = ns_mut["paginate"](items, 1, 3)
    except Exception:
        return  # raised: definitively not equivalent
    assert mutated != [1, 2, 3], "the mutant computes the same answer — equivalent, unkillable"


def test_arithmetic_and_constant_are_single_substitution_not_a_cross_product() -> None:
    """One mutant per site, not the 4-way arithmetic / six-way constant variants.

    Those are where the measured 31% and 57% duplication come from. For a gate, a duplicate is not
    merely wasted compute: every extra mutant is another independent chance to draw an equivalent
    one and refuse correct work.
    """
    src = "def f(a, b):\n    return a * b + 3\n"
    mutants = _all_mutations(src, {2}, cap=20)
    assert len(mutants) == len(set(mutants)), f"duplicate mutants generated: {mutants}"
    # `*`, `+` and the literal `3` are each one site — plus the return itself.
    assert 2 <= len(mutants) <= 5, f"expected single-substitution per site, got {len(mutants)}"


def test_a_numeric_literal_yields_a_mutant() -> None:
    src = "def f():\n    limit = 10\n    return limit\n"
    assert _mutate_source(src, {2}) is not None


def test_operators_stay_confined_to_the_changed_line() -> None:
    """Unchanged arithmetic elsewhere in the file must stay untouched — the whole point of the
    changed-line confinement is that the mutation lands on the delivered change, not on the first
    well-tested construct in the file."""
    src = "def untouched(a, b):\n    return a + b\n\n\ndef changed(x):\n    return x * 2\n"
    mutant = _mutate_source(src, {6})
    assert mutant is not None
    assert "a + b" in mutant, "an unchanged line was mutated"


def test_no_eligible_construct_still_returns_none() -> None:
    """Deny-by-default is preserved: a change with nothing mutable still yields no mutant.

    That is the honest `not_measured` case. It still declines for an unattended ship — the record
    changes, the outcome does not.
    """
    src = "import os\n\n\nCONFIG = os.environ\n"
    assert _mutate_source(src, {4}) is None


def test_arid_literals_are_not_mutated() -> None:
    """A timeout, a range bound and a default argument say nothing when perturbed.

    Changing `sleep(100)` to `sleep(101)` alters speed, not behaviour — no reasonable test kills it,
    so it is a manufactured survivor, which in this gate refuses correct work. Google's arid-node
    rules are the published source; suppressing this class is what took their mutant productivity
    from 15% to 89%, and skipping it would make constant mutation a wrongful-decline generator.
    """
    for src, line in [
        ("import time\n\n\ndef f():\n    time.sleep(100)\n", 5),
        ("def f(xs):\n    return [i for i in range(10)]\n", 2),
        ("def f(limit=10):\n    return limit\n", 1),
    ]:
        mutant = _mutate_source(src, {line})
        if mutant is not None:
            assert "11" not in mutant and "101" not in mutant, (
                f"an arid literal was perturbed in {src!r} -> {mutant!r}"
            )


def test_a_meaningful_literal_in_an_ordinary_call_IS_mutated() -> None:
    """The suppression is by called NAME, not "any literal in any call" — otherwise it would
    silence the operator almost everywhere. `total(100)` is behaviour; `sleep(100)` is not."""
    # An assignment, not a `return` — the single-mutation path tries kinds in order and a return
    # is matched first, which would mask the constant operator under test.
    mutant = _mutate_source("def f():\n    x = total(100)\n    return x\n", {2})
    assert mutant is not None and "101" in mutant


def test_booleans_are_never_perturbed() -> None:
    """`bool` is an `int` subclass in Python, so a naive numeric rule turns `True` into `2`.
    That is a nonsense mutant, not a behavioural one."""
    mutant = _mutate_source("def f():\n    cfg = dict(flag=True)\n    return cfg\n", {2})
    assert mutant is None or "True" in mutant


def test_identity_preserving_swaps_are_suppressed() -> None:
    """RED TEAM R2, confirmed and fixed. `x - 0` -> `x + 0` computes the same answer.

    An equivalent mutant is unkillable, and in THIS gate an unkillable mutant is a survivor, and a
    survivor refuses correct work. Standard mutation testing tolerates these because they bias a
    continuous score; ours is a binary ship veto, so each one is a wrongful decline. The `-` family
    is where about half of all AOR equivalents come from (Yao et al., ICSE 2014), which is exactly
    what R2 was pointed at.
    """
    for op, forbidden, ident in (("-", "+", 0), ("+", "-", 0), ("**", "*", 1), ("/", "*", 1)):
        src = f"def f(x):\n    y = x {op} {ident}\n    return y\n"
        # Only the OPERATOR must be suppressed. Perturbing the literal (`x - 0` -> `x - 1`) is the
        # const operator and IS behavioural — asserting the whole line is unchanged would wrongly
        # forbid that, which is how the first version of this test got it backwards.
        for mutant in _all_mutations(src, {2}, cap=20):
            assert f"x {forbidden} {ident}" not in mutant, (
                f"`x {op} {ident}` became `x {forbidden} {ident}` — that mutant computes the same "
                "answer, so no test can kill it and correct work is refused"
            )


def test_the_suppression_does_not_swallow_an_observable_swap() -> None:
    """`x * 1` -> `x / 1` stays: in Python that turns an int into a float, which a test can see.

    The suppression is by IDENTITY ELEMENT per operator, not "any literal 0 or 1 anywhere" — the
    lazy version would silence the operator across most real arithmetic for no correctness gain.
    """
    mutant = _mutate_source("def f(x):\n    y = x * 1\n    return y\n", {2})
    assert mutant is not None and "x / 1" in mutant


# --- D3: "could not measure" is not "failed" -------------------------------------------------


def test_not_measured_is_a_distinct_verdict() -> None:
    """`False` and `None` from the mutation check mean opposite things and shared one verdict.

    `unverified` = a real check said no (a rubber stamp). `not_measured` = the oracle could not
    form a question. Conflating them is what made 7 declines read as weak tests when they were an
    operator gap.
    """
    from typing import get_args

    from mosaera_core.disposition import Verdict

    assert "not_measured" in get_args(Verdict)


def test_every_non_verified_verdict_still_declines() -> None:
    """D3 changes the RECORD, never the outcome — pinned, not asserted in prose.

    Both ship tests in the codebase are POSITIVE (`== "verified"` / `!= "verified"`), so a new
    verdict can only ever leave the park standing. That is the same deny-preserving-by-construction
    property the gate-reason split relies on, and it is why adding a verdict is safe where adding a
    mutation operator is not.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    ship_tests = []
    for rel in (
        "core/mosaera_core/bench/layer2.py",
        "../apps/api/mosaera_api/app_context/_escalation.py",
    ):
        src = (root / rel).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Compare) and any(
                isinstance(c, ast.Constant) and c.value == "verified" for c in node.comparators
            ):
                ship_tests.append(type(node.ops[0]).__name__)
    assert ship_tests, "found no ship test — the guard drifted, not the code"
    assert set(ship_tests) <= {"Eq", "NotEq"}, (
        f"a ship test is not a positive comparison against 'verified': {ship_tests} — "
        "a new verdict could then permit a ship it was never reviewed for"
    )


# --- The cause behind `not_measured` must be MEASURED, not named ---------------------------------


def test_no_verdict_reason_separates_the_causes() -> None:
    """`suite_catches_a_mutation` returns None for no tests, no mutable source, OR no runnable
    execution — and the caller adds a fourth (it raised). F83's first draft printed *"no mutable
    construct in the change"* for **all four**.

    That is an unmeasured cause asserted in the one record whose entire job is separating causes —
    F83's own defect, one level up. Caught while reading the first post-fix sweep card, whose single
    data point rested on that exact string. So the reason asks the AST instead of guessing.
    """
    from types import SimpleNamespace

    from mosaera_core.mutation import has_mutable_construct, no_verdict_reason

    root = tmp = Path(__file__).parent / "_no_verdict_fixture"
    tmp.mkdir(exist_ok=True)
    try:
        (tmp / "mutable.py").write_text("def f(x):\n    return x * 2\n", encoding="utf-8")
        (tmp / "inert.py").write_text("import os\n\n\nCONFIG = os.environ\n", encoding="utf-8")
        ws = SimpleNamespace(root=root)

        assert has_mutable_construct(ws, ["mutable.py"], {"mutable.py": {2}}) is True
        assert has_mutable_construct(ws, ["inert.py"], {"inert.py": {4}}) is False

        # (a) it raised — never even reached the AST
        assert "errored" in no_verdict_reason(ws, ["mutable.py"], {"mutable.py": {2}}, failed=True)
        # (b) genuinely nothing to mutate — the claim is now true because it was checked
        assert "no mutable construct" in no_verdict_reason(
            ws, ["inert.py"], {"inert.py": {4}}, failed=False
        )
        # (c) mutable, yet no verdict — a DIFFERENT fault, and the one that used to be mislabelled
        other = no_verdict_reason(ws, ["mutable.py"], {"mutable.py": {2}}, failed=False)
        assert "IS mutable" in other and "no mutable construct" not in other
    finally:
        for p in tmp.iterdir():
            p.unlink()
        tmp.rmdir()


def test_the_shipping_verdict_records_what_it_audited() -> None:
    """A `verified` is the ONLY verdict that ships code with no human in the loop, so it is the one
    that most needs to be reconstructable — and it was the one left uninstrumented.

    Found on the first conversion this project ever produced: its card carried an empty
    `layer2_source` because the audited-files capture had been added to the decline path only.
    Pinned here so the shipping path can never again be the least auditable one.
    """
    import inspect

    from mosaera_core import disposition

    src = inspect.getsource(disposition.close_oracle_gap)
    tail = src[src.index('"verified",') :]
    assert '"source"' in tail, (
        "the `verified` return does not record the files it audited — the one verdict that "
        "ships unattended must be reconstructable after the workspace is reaped"
    )
