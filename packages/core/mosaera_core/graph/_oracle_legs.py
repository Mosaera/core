"""`oracle_verified` and the record of WHICH leg refused — computed together, from one evaluation.

**Why this module exists.** The oracle decision is an OR over four independence routes, ANDed with
the mutation and structural-spec floors:

    verified = (tester_vouched or standing_suite or test_cmd or structural_vouch)
               and mutation_ok and structural_ok

Measured on the 125-run baseline (`docs/engineering-history/corpus-baseline-2026-08-11.md`),
`oracle_unverified` is the largest sole cause of an **over-park** — a run that refused work the
hidden grader confirms was correct. But **nothing recorded which term was False**, so the cause had
to be inferred from the co-recorded `mutation_caught` on the scorecard. That inference cost a wrong
hypothesis on 2026-08-11, corrected only by re-querying the corpus before any code was written.

**Why the decision and the diagnosis are one function.** The alternative — compute the verdict in
the caller, describe it beside — lets the two drift, and a description that can disagree with the
decision it describes is worse than none. This session found five mechanisms that recorded less
than they claimed; the cheapest structural defence is to make the record a *byproduct of the
decision* rather than a parallel statement about it. `legs["verified"]` is the value the gate uses,
not a recomputation of it.

**Short-circuit is preserved deliberately.** `standing_suite` arrives as a callable because it walks
the workspace, and evaluating it eagerly would change cost — and any hidden behaviour — for every
run that never needed it. Legs the OR never reached record `NOT_EVALUATED`, which is honest: "we
did not ask" is a third state, distinct from "we asked and it said no". Collapsing those two is the
exact defect this module exists to end.

**`record_all` (default OFF) asks the remaining legs anyway, for the record only.** The
short-circuit answers "did SOMETHING vouch?" but not "would the standing suite have agreed?", and
that question is now load-bearing: 26 of 28 benchmark cases ship a real standing suite, and because
`tester_vouched` is evaluated first, every recent run recorded `standing_suite: not_evaluated`. The
engine reaches for the bar it just guessed and never learns whether the human-written one concurred.

The verdict is untouched by construction: OR is commutative, `independent` accumulates exactly as
before, and evaluation stops mattering the moment it is True — the extra calls only fill `legs`.
An exception from a leg the verdict DEPENDS on still propagates; one from a leg being polled purely
for the record is recorded as `<name>_error` and cannot change the outcome. Default OFF so the
production hot path keeps its workspace walk exactly as rationed above; the diagnostic sweep opts
in.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# A leg the short-circuiting OR never reached. NOT the same as False, and never counted as a
# blocker — a run vouched by the first route was not "refused" by the ones after it.
NOT_EVALUATED = "not_evaluated"

# The four independence routes, IN EVALUATION ORDER. Exported because the onboarding flow (#121)
# tells an operator which of these can vouch for their repo before the first run, and a second
# hand-written list of the same four names is the drift this module's own docstring is about. The
# names here ARE the keys `evaluate_oracle` records; `test_oracle_legs` pins that.
LEG_NAMES: tuple[str, ...] = (
    "tester_vouched",
    "standing_suite",
    "test_cmd",
    "structural_vouch",
)


def evaluate_oracle(
    *,
    tester_vouched: bool,
    standing_suite: Callable[[], bool],
    test_cmd: bool,
    structural_vouch: bool,
    mutation: bool | None,
    structural_spec: bool | None,
    sanctioned_edit: bool,
    mutation_vetoes: bool = True,
    mutation_cause: str = "",
    record_all: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """The oracle verdict, and the per-leg record of how it got there.

    ``mutation`` / ``structural_spec`` are the raw tri-states off `RunState`; both floors are
    deny-by-default in the sense that only a *proven* False parks — EXCEPT that a sanctioned test
    edit (ADR-0058 repair / ADR-0087 §5 amendment) tightens the mutation floor to vouch only on a
    proven catch, because the acceptance bar was renegotiated mid-run.

    Returns ``(verified, legs)``. The caller must use ``verified``; ``legs`` describes that exact
    evaluation and is safe to record verbatim.
    """
    legs: dict[str, Any] = {}
    independent = False
    thunks: dict[str, Callable[[], bool]] = {
        "tester_vouched": lambda: tester_vouched,
        "standing_suite": standing_suite,
        "test_cmd": lambda: test_cmd,
        "structural_vouch": lambda: structural_vouch,
    }
    # Driven by LEG_NAMES so the exported list and the evaluated one are the same list: a name
    # added to one and not the other raises here rather than quietly under-recording.
    for name in LEG_NAMES:
        leg = thunks[name]
        if independent and not record_all:
            legs[name] = NOT_EVALUATED  # the OR was already satisfied; we never asked
            continue
        # True here means the verdict is already settled and this call is PURELY observational, so
        # its failure must not be able to park a run that something already vouched for.
        observational = independent
        try:
            value = bool(leg())
        except Exception as exc:
            if not observational:
                raise  # a leg the verdict DEPENDS on: never swallowed
            legs[f"{name}_error"] = repr(exc)[:200]
            value = False
        legs[name] = value
        independent = independent or value

    # Only a proven False blocks — UNLESS this run's tests were edited under sanction, where an
    # unmeasured mutation no longer vouches (ADR-0087's named backstop for its accepted
    # semantic-weakening residual). Gaming is closed by coder-blind timing, but an honest
    # over-relax could still ship, so that path demands a PROVEN catch.
    #
    # `mutation_vetoes=False` is the A/B's arm B: a proven surviving mutation stops blocking and is
    # merely recorded. It removes THAT and nothing else — a sanctioned edit still demands a proven
    # catch, so ADR-0087's backstop stands and the arms differ in exactly one behaviour. (The
    # measured target: 7 firings on the 125-run baseline, all 7 refusing correct work, 0 true
    # positives — in a corpus with 0 false ships, so the benefit is unmeasured, not disproven.)
    if sanctioned_edit:
        mutation_ok = mutation is not None if not mutation_vetoes else mutation is True
    else:
        mutation_ok = True if not mutation_vetoes else mutation is not False
    structural_ok = structural_spec is not False

    legs["independent"] = independent
    legs["sanctioned_test_edit"] = sanctioned_edit
    legs["mutation_ok"] = mutation_ok
    legs["mutation_raw"] = mutation
    # WHY there is no verdict, when there is none — "we never looked" and "we looked and
    # could not tell" both park under ADR-0087's backstop and were indistinguishable.
    legs["mutation_cause"] = mutation_cause
    # Which ARM produced this row. Without it the two sweeps are indistinguishable in the corpus
    # after the fact, which is how an A/B becomes unreadable a week later.
    legs["mutation_vetoes"] = mutation_vetoes
    legs["structural_ok"] = structural_ok
    legs["structural_raw"] = structural_spec
    # The direct answer to "which term refused?" — the question the corpus could not answer, and
    # the reason a whole hypothesis had to be discarded. Ordered as the AND is written.
    legs["blocked_by"] = [
        name
        for name, ok in (
            ("independence", independent),
            ("mutation", mutation_ok),
            ("structural", structural_ok),
        )
        if not ok
    ]
    legs["verified"] = verified = independent and mutation_ok and structural_ok
    return verified, legs
