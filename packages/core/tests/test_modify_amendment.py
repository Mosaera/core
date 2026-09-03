"""The Proctor is told WHICH pre-existing test asserts the behaviour an item changes (slice 4).

Measured 2026-08-10 on the 52-run integration sweep: MCB-28 delivered 0/2. Run 1 stalled at
iteration 1 with `tests_tampered` — *"pre-existing/protected tests were modified:
tests/test_pricing.py"* — which is the deadlock slice 4 exists to break, unbroken. Slice 4's
`consumer_impact` oracle ran and returned SATISFIED; the oracle was never the problem.

The cause is an ordering trap with no autonomous exit: the item requires editing the test, editing
it sets `tests_modified`, and `amendment_offer` then returns `{}` BY DESIGN ("a run that already
TAMPERED may not be handed authorization to amend"). The sanctioned route needs a HUMAN, and
`amendment_gate` is default-OFF and outside `apply_oracle_posture` — inert for all 52 runs.

This adds no authority: ADR-0058 already lets the Proctor repair pre-existing tests, once,
coder-blind, content-pinned into `proctor_edits`. It only NAMES the target, exactly as the
faithfulness guard does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from mosaera_core.graph._modify_amendment import (
    _modify_amendment_block,
    _modify_amendment_targets,
)


class _WS:
    def __init__(self, root: Path) -> None:
        self.root = root


class _Settings:
    proctor_faithfulness_guard = False


class _Ctx:
    def __init__(self, root: Path) -> None:
        self.workspace = _WS(root)
        self.settings = _Settings()


def _tree(tmp: Path) -> Path:
    (tmp / "pricing").mkdir(parents=True, exist_ok=True)
    (tmp / "tests").mkdir(parents=True, exist_ok=True)
    (tmp / "pricing" / "discount.py").write_text(
        "def apply_discount(total, pct):\n    return total * (1 - pct / 100)\n", encoding="utf-8"
    )
    (tmp / "tests" / "test_pricing.py").write_text(
        "from pricing.discount import apply_discount\n\n"
        "def test_raw() -> None:\n    assert apply_discount(10.0, 17) == 8.299999999999999\n",
        encoding="utf-8",
    )
    return tmp


def _claim(**over: Any) -> Any:
    base = {
        "id": "task-c1",
        "text": "Change `apply_discount` to return the discounted total rounded to two decimals",
        "oracle_kind": "consumer_impact",
        "provenance": "ENTAILED",
        "material": True,
    }
    base.update(over)
    return base


def _state(tmp: Path, **over: Any) -> Any:
    base: dict[str, Any] = {
        "claims": [_claim()],
        "integrity_baseline": {"tests/test_pricing.py": "deadbeef"},
        "task": "round discounted prices",
    }
    base.update(over)
    return base


def test_the_old_behaviour_test_is_named(tmp_path: Path) -> None:
    """THE FIX. The Proctor is pointed at the exact file the coder may not touch."""
    ctx = _Ctx(_tree(tmp_path))
    targets = _modify_amendment_targets(cast(Any, ctx), _state(tmp_path))
    assert [t[2] for t in targets] == ["tests/test_pricing.py"]
    assert targets[0][1] == "apply_discount"


def test_the_block_says_RESTATE_never_delete(tmp_path: Path) -> None:
    """The assertion-profile check downstream refuses the tamper excuse for any repair that drops
    or shrinks a test function, so an instruction inviting removal would produce a park."""
    block = _modify_amendment_block(cast(Any, _Ctx(_tree(tmp_path))), _state(tmp_path))
    assert "tests/test_pricing.py" in block
    assert "restate" in block.lower()
    assert "do NOT delete" in block
    assert "weaken" in block


def test_a_test_authored_THIS_run_is_not_a_pre_existing_bar(tmp_path: Path) -> None:
    """Not in `integrity_baseline` ⇒ not a pre-existing bar. Pointing the Proctor at its own
    output is a loop, not an amendment."""
    ctx = _Ctx(_tree(tmp_path))
    assert _modify_amendment_targets(cast(Any, ctx), _state(tmp_path, integrity_baseline={})) == []


def test_an_INFERRED_claim_never_authorizes_an_amendment(tmp_path: Path) -> None:
    """Only sentences quoted from the acceptance text the operator approved. A model proposal
    must not be able to nominate a test for rewriting."""
    ctx = _Ctx(_tree(tmp_path))
    state = _state(tmp_path, claims=[_claim(provenance="INFERRED")])
    assert _modify_amendment_targets(cast(Any, ctx), state) == []


def test_a_non_modify_claim_names_nothing(tmp_path: Path) -> None:
    ctx = _Ctx(_tree(tmp_path))
    state = _state(tmp_path, claims=[_claim(oracle_kind="acceptance_test")])
    assert _modify_amendment_targets(cast(Any, ctx), state) == []
    assert _modify_amendment_block(cast(Any, ctx), state) == ""


def test_a_claim_naming_no_symbol_names_no_test(tmp_path: Path) -> None:
    ctx = _Ctx(_tree(tmp_path))
    state = _state(
        tmp_path, claims=[_claim(text="Change the output so it prints one row per entry")]
    )
    assert _modify_amendment_targets(cast(Any, ctx), state) == []


def test_only_tests_referencing_THAT_symbol_are_named(tmp_path: Path) -> None:
    """Scoped by AST reference, not by 'every baselined test'."""
    root = _tree(tmp_path)
    (root / "tests" / "test_unrelated.py").write_text(
        "def test_other() -> None:\n    assert 1 == 1\n", encoding="utf-8"
    )
    ctx = _Ctx(root)
    state = _state(
        tmp_path,
        integrity_baseline={"tests/test_pricing.py": "a", "tests/test_unrelated.py": "b"},
    )
    assert [t[2] for t in _modify_amendment_targets(cast(Any, ctx), state)] == [
        "tests/test_pricing.py"
    ]


def test_no_claims_no_block(tmp_path: Path) -> None:
    """Byte-identical to today for every item that is not a MODIFY."""
    ctx = _Ctx(_tree(tmp_path))
    assert _modify_amendment_block(cast(Any, ctx), _state(tmp_path, claims=[])) == ""


def _collision_tree(tmp: Path) -> Path:
    """Two modules defining the SAME symbol name, each with its own pre-existing test."""
    for d in ("pricing", "billing", "tests"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    (tmp / "pricing" / "discount.py").write_text(
        "def apply(total, pct):\n    return total * (1 - pct / 100)\n", encoding="utf-8"
    )
    (tmp / "tests" / "test_pricing.py").write_text(
        "from pricing.discount import apply\n\ndef test_p():\n    assert apply(10, 10) == 9\n",
        encoding="utf-8",
    )
    (tmp / "billing" / "invoice.py").write_text(
        "class Tax:\n    def apply(self, x):\n        return x * 1.2\n", encoding="utf-8"
    )
    (tmp / "tests" / "test_billing.py").write_text(
        "from billing.invoice import Tax\n\ndef test_tax():\n    assert Tax().apply(100) == 120\n",
        encoding="utf-8",
    )
    return tmp


_BOTH_BASELINED = {"tests/test_pricing.py": "a", "tests/test_billing.py": "b"}


def test_a_name_collision_does_not_hand_out_an_unrelated_test(tmp_path: Path) -> None:
    """RED TEAM R2, CONFIRMED 2026-08-11 and fixed. `consumers_of` matches a BARE NAME —
    `_symbol_of` discards the module path and `_references_in` matches any `ast.Attribute.attr` —
    so `pricing.discount.apply` nominated a test asserting `Tax().apply(100) == 120`.

    Why it mattered: a nominated test may be REWRITTEN under the tamper excuse, so the guard stands
    down on a contract nothing asked to change. ADR-0097's "over-matching is harmless by
    construction" is true of the ORACLE (it only refuses more) and false here, where the same
    enumeration picks files the Proctor may edit.
    """
    ctx = _Ctx(_collision_tree(tmp_path))
    state = _state(
        tmp_path,
        claims=[_claim(text="Change `pricing.discount.apply` to round to two decimals")],
        integrity_baseline=dict(_BOTH_BASELINED),
    )
    named = sorted(t[2] for t in _modify_amendment_targets(cast(Any, ctx), state))
    assert named == ["tests/test_pricing.py"], (
        f"the unrelated test was nominated by name collision: {named}"
    )


def test_the_real_consumer_is_still_named_through_the_narrowing(tmp_path: Path) -> None:
    """The positive control. A narrowing that nominated NOTHING would pass the test above while
    silently disabling the whole mechanism — the failure mode this session keeps finding."""
    ctx = _Ctx(_collision_tree(tmp_path))
    state = _state(
        tmp_path,
        claims=[_claim(text="Change `pricing.discount.apply` to round to two decimals")],
        integrity_baseline=dict(_BOTH_BASELINED),
    )
    assert [t[2] for t in _modify_amendment_targets(cast(Any, ctx), state)] == [
        "tests/test_pricing.py"
    ]
    assert _modify_amendment_block(cast(Any, ctx), state) != "", "the block must still render"


def test_an_AMBIGUOUS_bare_symbol_nominates_nothing(tmp_path: Path) -> None:
    """Deny-by-default. A bare `apply` with two definitions in the tree gives no way to tell which
    behaviour the item changes, and handing out edit rights on a guess is the unsafe direction."""
    ctx = _Ctx(_collision_tree(tmp_path))
    state = _state(
        tmp_path,
        claims=[_claim(text="Change `apply` to round to two decimals")],
        integrity_baseline=dict(_BOTH_BASELINED),
    )
    assert _modify_amendment_targets(cast(Any, ctx), state) == []
