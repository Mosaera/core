"""`record_all` buys observability and MUST NOT buy anything else (#129).

The whole safety argument for this knob is that OR is commutative: polling the legs the
short-circuit skipped cannot change `verified`, because `independent` accumulates the same way. If
that is ever false the knob is a trust-boundary change rather than an instrument, so the tests that
matter here are the ones asserting the verdict is IDENTICAL across both arms.

Context: `tester_vouched` is evaluated first, so `standing_suite` recorded `not_evaluated` on every
run — the engine never learned whether the human-written suite agreed with the one it guessed.
"""

from __future__ import annotations

import pytest
from mosaera_core.graph._oracle_legs import NOT_EVALUATED, evaluate_oracle


def _call(*, record_all: bool, standing: object = True, **kw: object):
    calls: list[str] = []

    def standing_suite() -> bool:
        calls.append("standing")
        if isinstance(standing, Exception):
            raise standing
        return bool(standing)

    verified, legs = evaluate_oracle(
        tester_vouched=bool(kw.get("tester_vouched", True)),
        standing_suite=standing_suite,
        test_cmd=bool(kw.get("test_cmd", False)),
        structural_vouch=bool(kw.get("structural_vouch", False)),
        mutation=kw.get("mutation", True),  # type: ignore[arg-type]
        structural_spec=kw.get("structural_spec", True),  # type: ignore[arg-type]
        sanctioned_edit=bool(kw.get("sanctioned_edit", False)),
        record_all=record_all,
    )
    return verified, legs, calls


@pytest.mark.parametrize(
    "kw",
    [
        {"tester_vouched": True},
        {"tester_vouched": False},
        {"tester_vouched": True, "test_cmd": True},
        {"tester_vouched": False, "test_cmd": True},
        {"tester_vouched": False, "mutation": False},
        {"tester_vouched": True, "structural_spec": False},
        {"tester_vouched": True, "sanctioned_edit": True, "mutation": None},
    ],
)
@pytest.mark.parametrize("standing", [True, False])
def test_the_verdict_is_IDENTICAL_in_both_arms(kw: dict, standing: bool) -> None:
    """THE load-bearing property. If this ever fails, the knob is not diagnostic."""
    off, _, _ = _call(record_all=False, standing=standing, **kw)
    on, _, _ = _call(record_all=True, standing=standing, **kw)
    assert off == on, f"record_all changed the verdict for {kw} / standing={standing}"


def test_OFF_still_short_circuits_and_does_not_walk_the_workspace() -> None:
    """The rationing the module docstring defends: a vouched run must not pay for the walk."""
    _, legs, calls = _call(record_all=False, tester_vouched=True)
    assert calls == [], "the standing-suite thunk was called despite an earlier vouch"
    assert legs["standing_suite"] == NOT_EVALUATED


def test_ON_replaces_not_evaluated_with_a_real_answer() -> None:
    """The point of the knob: the question the corpus could not answer."""
    _, legs, calls = _call(record_all=True, tester_vouched=True, standing=False)
    assert calls == ["standing"]
    assert legs["standing_suite"] is False, "the disagreement must be recorded, not elided"
    assert legs["tester_vouched"] is True
    assert legs["independent"] is True


def test_ON_records_agreement_too() -> None:
    _, legs, _ = _call(record_all=True, tester_vouched=True, standing=True)
    assert legs["tester_vouched"] is True and legs["standing_suite"] is True


def test_an_observational_leg_that_RAISES_cannot_park_a_vouched_run() -> None:
    """`standing_suite` walks a real workspace, so ON introduces a call that OFF never made. A run
    something already vouched for must not start failing because of a poll taken for the record."""
    verified, legs, _ = _call(
        record_all=True, tester_vouched=True, standing=RuntimeError("walk exploded")
    )
    assert verified is True
    assert legs["standing_suite"] is False
    assert "walk exploded" in legs["standing_suite_error"]


def test_a_leg_the_VERDICT_DEPENDS_ON_still_raises() -> None:
    """The other half, and the one a bare `except` would silently break: when nothing has vouched
    yet, the standing suite decides — and an error there must never be read as a quiet False."""
    with pytest.raises(RuntimeError):
        _call(record_all=True, tester_vouched=False, standing=RuntimeError("walk exploded"))


def test_no_error_key_appears_on_the_happy_path() -> None:
    """A diagnostic that cries wolf is worse than none."""
    _, legs, _ = _call(record_all=True, tester_vouched=True, standing=True)
    assert not [k for k in legs if k.endswith("_error")]
