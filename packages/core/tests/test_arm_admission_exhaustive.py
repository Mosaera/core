"""Every arm must have an OPINION about every reason class — enforced, not remembered (ADR-0107).

The defect this closes, stated once: `REASON_CLASS` classifies for more than one decision, and the
decisions do not carry the same risk. Adding a class, or a reason, silently gives every arm a new
member it has never considered — and because admission is `set(reasons) - allowed`, the default for
an unconsidered class is *deny*. For the SHIP arm that is correct and deliberate. For the ASK arm it
is how the ask died: `security_not_attempted`'s predecessor landed in `objection` by inheritance,
the give-up path guarantees it, and the arm refused to speak on 100% of the runs it could reach.

`mypy` alone cannot catch this. `_ASK_ADMISSIBLE_CLASSES` is a `tuple[ReasonClass, ...]`, so adding
a fifth `ReasonClass` member typechecks fine while leaving the tuple silently short. The totality
guard in `test_gate_reason_classification.py` proves every *reason* has a class; this proves every
*class* has been dispositioned by every *arm*.

The rule is not "every arm admits everything" — the arms genuinely differ, and that difference is
the fix. The rule is that the difference is DECLARED.
"""

from __future__ import annotations

import typing

from mosaera_core.eligibility import _ADMISSIBLE_CLASSES, give_up_allowed_reasons
from mosaera_core.escalate_arm import _ASK_ADMISSIBLE_CLASSES, ask_allowed_reasons
from mosaera_policies import REASON_CLASS, ReasonClass, reasons_of_class

_ALL_CLASSES: frozenset[str] = frozenset(typing.get_args(ReasonClass))

# Every arm that answers a question by intersecting the shared classification, with the classes it
# deliberately REFUSES. A new arm belongs here on the day it is written.
_ARMS: dict[str, tuple[tuple[str, ...], frozenset[str]]] = {
    # "May this parked run be DELIVERED?" — deletes tests, commits, opens an MR. "We never looked"
    # must disqualify it; that is ADR-0076's deny-by-default and it is not being relaxed.
    "ship": (_ADMISSIBLE_CLASSES, frozenset({"objection", "tamper", "not_run"})),
    # "May I ASK the operator a question?" — writes one `direction` clarification and nothing else.
    "ask": (_ASK_ADMISSIBLE_CLASSES, frozenset({"objection", "tamper"})),
}


def test_every_arm_dispositions_every_class() -> None:
    """Add a `ReasonClass` and this fails until each arm says admit or refuse. That is the point."""
    for arm, (admitted, refused) in _ARMS.items():
        considered = set(admitted) | set(refused)
        assert considered == _ALL_CLASSES, (
            f"the {arm!r} arm has not dispositioned {sorted(_ALL_CLASSES - considered)} — "
            "an unconsidered class silently defaults to REFUSED, which is how the ask died"
        )
        assert not (set(admitted) & refused), f"{arm!r} both admits and refuses a class"


def test_tamper_is_admitted_by_no_arm() -> None:
    """The one line no arm may ever cross, asserted over arms rather than over one arm."""
    for arm, (admitted, _) in _ARMS.items():
        assert "tamper" not in admitted, f"{arm!r} admits tamper"
    # And concretely, because `ask_withheld_reason`'s own tamper check reads `tests_modified` while
    # ADR-0099's `content_destroyed` derives from `destroyed_paths` — so ONLY class membership
    # keeps a destroyed-content park out of the ask.
    assert "content_destroyed" not in ask_allowed_reasons()
    assert "content_destroyed" not in give_up_allowed_reasons()


def test_the_arms_differ_by_exactly_not_run() -> None:
    """The ADR-0107 delta, pinned. If these sets ever converge, one of two things happened: the ask
    was re-silenced, or the SHIP arm quietly started admitting unscanned code. Both are regressions
    and neither would fail any other test."""
    assert ask_allowed_reasons() - give_up_allowed_reasons() == reasons_of_class("not_run")
    assert not (give_up_allowed_reasons() - ask_allowed_reasons())


def test_the_give_up_paths_not_run_reasons_are_admitted_to_the_ask() -> None:
    """Concretely, the two reasons the bypass edges produce (`graph/build.py` routes plan-unworkable
    and supervise-give-up straight to the gate, skipping `scan_node` and `test_node`)."""
    assert {"security_not_attempted", "validation_not_attempted"} <= ask_allowed_reasons()
    # ...and still refused by the SHIP arm, which is the half that must not move.
    assert not ({"security_not_attempted", "validation_not_attempted"} & give_up_allowed_reasons())


def test_a_ran_and_objected_reason_is_admitted_by_neither() -> None:
    """`not_run` means the check never executed — never "it ran and we dislike the answer". The
    reasons that mean a check RAN and produced nothing usable stay objections for both arms."""
    for reason in ("security_unverified", "validation_unavailable"):
        assert REASON_CLASS[reason] == "objection"
        assert reason not in ask_allowed_reasons()
        assert reason not in give_up_allowed_reasons()
