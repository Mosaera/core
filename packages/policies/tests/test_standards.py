"""The clause vocabulary (ADR-0082 tiers 1-2) — chiefly, what it CANNOT say.

A policy layer that can express "skip the check" is a waiver mechanism wearing a governance
costume. These tests are the argument that it cannot.
"""

from __future__ import annotations

from typing import get_args

import pytest
from mosaera_policies.gate import GateReason
from mosaera_policies.standards import (
    CONDITION_PARAMS,
    PARAMS,
    PROOF_BEARING,
    STANDARDS,
    validate_clause,
)


def _clause(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "standard_id": "standards/house-style",
        "binds": "structural.body_statements",
        "value_kind": "number",
        "value_num": 5,
    }
    base.update(over)
    return base


def test_the_first_clause_is_expressible() -> None:
    """The decision measured on 2026-08-04: "a short orchestrator means at most 5 statements".

    ADR-0082's own definition-of-done says that if a clause cannot express the MCB-05/15 decision,
    the design failed. This is that clause.
    """
    assert validate_clause(_clause()) == ""


@pytest.mark.parametrize("reason", sorted(get_args(GateReason)))
def test_no_registered_parameter_reaches_a_proof_bearing_reason(reason: str) -> None:
    """Driven off the gate's OWN vocabulary, so the test grows when the vocabulary grows.

    That is the executable form of "checked at write and read time": a new gate reason cannot be
    added without this test asking whether a clause can now touch it.
    """
    if reason not in PROOF_BEARING:
        return
    reachable = [name for name, p in PARAMS.items() if p.affects == reason]
    assert not reachable, (
        f"{reachable} can influence {reason!r}, a proof-bearing reason — that parameter is a "
        "waiver, not a setting"
    )


def test_a_standards_own_enforced_constant_is_unregistrable() -> None:
    """The 500-line ceiling cannot be rebound, because there is no NAME for it.

    Not "it is denied" — denial is a rule someone can amend. The parameter simply does not exist,
    so "waive the god-file ceiling" cannot be written down. Two independent refusals, and the
    messages differ because the nets are independent.
    """
    unnamed = validate_clause(_clause(binds="module.max_lines", value_num=800))
    assert "not a registered oracle parameter" in unnamed

    # And even a REGISTERED parameter is refused when the cited standard fixes it rather than
    # leaving it open — the second net, verified separately.
    not_open = validate_clause(
        _clause(standard_id="standards/layer-direction", binds="structural.body_statements")
    )
    assert "does not leave" in not_open
    assert unnamed != not_open


def test_a_clause_cannot_name_a_verdict_or_an_oracle() -> None:
    for binds in ("gate.verdict", "oracle.enabled", "claims.satisfied", "validation_failed"):
        assert "not a registered oracle parameter" in validate_clause(_clause(binds=binds))


def test_an_unknown_standard_is_refused_which_is_also_the_staleness_path() -> None:
    """No expiry dates: a clause's validity is a FUNCTION of its parent (ADR-0082 section 3).

    Retire or rename a standard and every clause citing it stops validating at load — staleness
    by construction rather than calendar ceremony.
    """
    assert "unknown standard" in validate_clause(_clause(standard_id="standards/retired"))


def test_values_are_numbers_never_prose() -> None:
    # The whole failure this arc exists for is a value that had to be re-derived from text.
    assert "needs an integer value" in validate_clause(_clause(value_num="a handful"))
    assert "needs an integer value" in validate_clause(_clause(value_num=None))
    assert "outside" in validate_clause(_clause(value_num=9999))
    assert "unknown value kind" in validate_clause(_clause(value_kind="whatever"))
    # A non-numeric clause carries no number at all, rather than a silently ignored one.
    assert validate_clause(_clause(value_kind="advisory", value_num=None)) == ""
    assert "carries no number" in validate_clause(_clause(value_kind="advisory", value_num=5))


def test_a_condition_is_all_or_nothing_and_draws_from_its_own_vocabulary() -> None:
    assert validate_clause(_clause(when_param="module_lines", when_op="<", when_num=500)) == ""
    assert "all of parameter" in validate_clause(_clause(when_param="module_lines"))
    assert "unknown condition parameter" in validate_clause(
        _clause(when_param="gate.verdict", when_op="<", when_num=1)
    )
    # A condition cannot borrow the bindable vocabulary, or it becomes a second way to name things.
    assert not (CONDITION_PARAMS & set(PARAMS))


def test_every_standard_is_backed_by_something_that_already_has_teeth() -> None:
    """Tier 1 is bootstrapped from guards that already fail CI, so it starts as fact.

    ADR-0082: "a clause with nothing to cite is the free-floating exception this ADR exists to
    avoid."
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    for standard in STANDARDS.values():
        assert standard.scope in ("repo", "project"), standard.id
        assert (root / standard.enforced_by).is_file(), (
            f"{standard.id} cites {standard.enforced_by}, which does not exist"
        )
        for param in standard.open_params:
            assert param in PARAMS, f"{standard.id} leaves unregistered {param!r} open"


def test_refusal_is_the_default_for_anything_unrecognised() -> None:
    assert validate_clause(None) == "not a clause record"
    assert validate_clause({}) != ""
    assert validate_clause(_clause(binds="")) != ""


def test_the_registry_invariants_are_raised_not_asserted() -> None:
    """`python -O` strips asserts. An invariant that vanishes under an optimisation flag is not
    a guarantee, so the import-time checks raise — and are callable, hence testable."""
    from unittest.mock import patch

    from mosaera_policies import standards as mod

    with patch.dict(mod.PARAMS, {"x.y": mod.OracleParam("x.y", "int", 1, 2, "tests_tampered")}):
        with pytest.raises(RuntimeError, match="waiver, not a setting"):
            mod._verify_registries()

    with patch.object(mod, "PROOF_BEARING", frozenset({"a_reason_gate_never_had"})):
        with pytest.raises(RuntimeError, match="GateReason no longer has"):
            mod._verify_registries()
