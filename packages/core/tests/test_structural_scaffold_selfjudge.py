"""A structural contract must not judge the engine's own scaffolding as the agent's work.

**The defect, measured 2026-08-12.** MCB-15 (a refactor case) parked 5/5 with
`claim_structural_failed` while the hidden grader PASSED all seven of its tests — including its own
two structural ones. The
recorded reason was *"`parse_log_line` is 13 statements where it was 13 … delegates to 0 module
helper(s)"* — the shape of the code BEFORE the refactor.

The delivered `logparse.py` was a textbook refactor (4 statements, three module-level helpers), and
`check_structural_compliance` passes it. What failed was a second file: the refactor scaffold
(ADR-0066) writes a golden-master snapshot to `tests/_frozen_logparse.py` holding the pre-refactor
function verbatim. That basename does not match the pytest pattern, so `is_test_file` returned False
and it entered "delivered sources". The red-team R2 rule — judge EVERY changed file defining the
target, so a trivially-compliant decoy cannot shadow a bloated real one — then made the frozen
copy's inevitable failure authoritative.

**A frozen copy of the original can never satisfy "refactor this", by construction.** So this was a
deterministic false-park generator on exactly the cases the scaffold exists to help.

**Reverted once, then RE-LANDED 2026-08-12 with the ratified clause.** Wiring this in alone
fixed MCB-15 (over-park 4/5 -> 0/5, 5/5
delivered) and simultaneously produced **2 false ships on MCB-05**, which had delivered 0/5 before.
The frozen copy was accidentally masking a second defect: a satisfied `ast_transformation_contract`
claim mints a structural independence VOUCH that clears `oracle_unverified`, and the engine's
shrink-ratio predicate is more permissive than the case's own acceptance test. Removing the
accidental block let that through.

It is now **applied in `_delivered_sources`, together with the ratified
`structural.body_statements=5` bench default** that closes the exposed gap (ledger E5:
delivered 7→18, over-park 8→2, false ships 0 across the four refactor cases).
`is_test_file` is shared with the ADR-0036 tamper guard and is deliberately NOT widened
either way.
"""

from __future__ import annotations

from mosaera_core.claim_oracles import _in_test_tree


def test_the_scaffolds_frozen_snapshot_is_not_delivered_source() -> None:
    """THE DEFECT. `tests/_frozen_<module>.py` is engine scaffolding, not agent work."""
    assert _in_test_tree("tests/_frozen_logparse.py") is True


def test_ordinary_source_is_still_judged() -> None:
    """THE POSITIVE CONTROL. A filter that excluded everything would 'fix' the false park by
    disabling the check — which is the failure mode this repo keeps finding."""
    assert _in_test_tree("logparse.py") is False
    assert _in_test_tree("pkg/service.py") is False
    assert _in_test_tree("src/pricing/discount.py") is False


def test_nested_and_singular_test_directories_are_covered() -> None:
    assert _in_test_tree("src/tests/helpers.py") is True
    assert _in_test_tree("test/fixtures.py") is True


def test_a_file_merely_NAMED_like_a_test_dir_is_still_source() -> None:
    """Only path COMPONENTS count. `tests.py` and `latest/` are ordinary source."""
    assert _in_test_tree("tests.py") is False
    assert _in_test_tree("latest/build.py") is False
    assert _in_test_tree("contest/entry.py") is False
