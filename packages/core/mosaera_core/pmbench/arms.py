"""Compare two models on identical trials — and refuse to name a winner that wasn't earned.

Shaped on `bench/liveness.ExperimentReport`, where *"`effect is None` is the enforcement"*: a
comparison that cannot support a claim returns no claim, rather than a number a reader will quote
anyway. Its warning is the exact trap this module has to avoid, and it transfers word for word:

    "What this does NOT do, deliberately: accept 'the arms' RESULTS differed' as validity. Two runs
    of one configuration produce different outcomes routinely — that is model nondeterminism, not an
    effect — so scoring on result-divergence would license attributing noise to the lever."

Two models producing different text is expected and proves nothing. Only a difference exceeding
what one model produces against itself is evidence, which is why `null_control` is not optional
decoration but the thing the verdict is measured against.

**Paired, on (case, pass index).** Concordant trials — both right or both wrong — are discarded,
because they say nothing about which model is better. That discarding is the whole economy of the
design: it needs ~12 to 39 discordant trials where an absolute ±0.05 score would need ~196.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from mosaera_core.pmbench.stats import discordant_needed, mcnemar_exact

#: A verdict is only quoted below this. Fixed here, before any data — the repo's rule is that power
#: is "pre-registered so a small result reads as underpowered, never as no effect".
ALPHA = 0.05

#: The one dimension whose result carries a verdict. Fixed HERE, with its reason, because a primary
#: chosen after seeing data is not a primary.
#:
#: Testing four dimensions at alpha=0.05 gives an 18.5% chance of naming a spurious winner, which is
#: not a rate an instrument that picks a production model may run at. The repo's standing answer to
#: that is pre-registration rather than blanket correction — decision rules fixed before the data
#: and conjunctive (`compare_arms.py:185`, `ADR-0083`: "the case IS the pre-registration").
#:
#: `safe` is the choice because its failures are the irreversible ones. A wrong completeness call
#: costs a re-run; a wrong safety call deletes the record of delivered work, which is precisely what
#: a live PM proposed on 2026-08-19 and what the changeset guard now refuses. Every other dimension
#: is reported and can never, on its own, name a winner.
PRIMARY_DIMENSION = "safe"

TOO_CLOSE = "TOO_CLOSE_TO_CALL"
SECONDARY_NOT_DECISIVE = "SECONDARY_DIMENSION_CANNOT_NAME_A_WINNER"
NO_DISAGREEMENT = "ARMS_NEVER_DISAGREED"
#: Retained for callers that pinned the old verdict name; the count-threshold gate it named was
#: removed as unsound (see `compare_arms`). A null control now calibrates rather than filters.
BELOW_NULL_FLOOR = "WITHIN_THE_MEASURED_NOISE_FLOOR"


@dataclass(frozen=True)
class ArmComparison:
    """Which model won, or why the question cannot be answered from this data.

    ``winner is None`` is the enforcement. A caller that wants a name must handle not getting one.
    """

    arm_a: str
    arm_b: str
    a_only: int  # trials A passed and B failed
    b_only: int  # trials B passed and A failed
    concordant: int
    p_value: float
    winner: str | None = None
    verdict: str | None = None
    needed: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def discordant(self) -> int:
        return self.a_only + self.b_only


def _paired(
    a: dict[tuple[str, str, int], bool], b: dict[tuple[str, str, int], bool]
) -> tuple[int, int, int]:
    """Count (a_only, b_only, concordant) over trials BOTH arms actually ran.

    Only shared keys are compared. `compare_arms._by_case` takes the same precaution and refuses on
    an empty intersection: *"Comparing like case with like removes that variance entirely, which is
    the whole reason an enriched design buys more power per GPU-hour."*
    """
    a_only = b_only = concordant = 0
    for key in a.keys() & b.keys():
        pa, pb = a[key], b[key]
        if pa == pb:
            concordant += 1
        elif pa:
            a_only += 1
        else:
            b_only += 1
    return a_only, b_only, concordant


def compare_arms(
    arm_a: str,
    arm_b: str,
    trials_a: dict[tuple[str, str, int], bool],
    trials_b: dict[tuple[str, str, int], bool],
    *,
    null_floor: int | None = None,
    alpha: float = ALPHA,
) -> ArmComparison:
    """Paired comparison of two arms. ``winner`` is set only when the evidence earns it.

    ``null_floor`` is the discordant count observed when one model was run against ITSELF. A real
    difference must exceed it; without it the comparison still runs, but says so in its notes,
    because a floor that is assumed rather than measured is the defect
    `compare_arms.py:181-183` warns about ("a hardcoded number that silently ages").
    """
    a_only, b_only, concordant = _paired(trials_a, trials_b)
    discordant = a_only + b_only
    p = mcnemar_exact(a_only, b_only)
    notes: list[str] = []

    if not (trials_a.keys() & trials_b.keys()):
        return ArmComparison(
            arm_a,
            arm_b,
            0,
            0,
            0,
            1.0,
            None,
            TOO_CLOSE,
            0,
            ("no trial was run by both arms — nothing is paired, so nothing is comparable",),
        )

    if discordant == 0:
        return ArmComparison(
            arm_a,
            arm_b,
            0,
            0,
            concordant,
            1.0,
            None,
            NO_DISAGREEMENT,
            0,
            (
                f"the arms agreed on all {concordant} paired trials; that is not evidence they are "
                "equal, it is the absence of any evidence either way",
            ),
        )

    if null_floor is None:
        notes.append("no null control was run — this test's calibration is unverified")
    else:
        # The null control is a CALIBRATION check, not a threshold. Its first version treated the
        # discordant COUNT as a bar to exceed, which is wrong twice over: under the null hypothesis
        # discordant pairs split 50/50 and McNemar already accounts for that, and a real comparison
        # with exactly as many discordant trials as the null control but a 13-to-1 split is strong
        # evidence that the count-gate would have thrown away.
        #
        # What the floor is genuinely for: POWER. A model that disagrees with itself on 14 of 72
        # trials says how much sampling noise a real difference has to show through, which is an
        # input to how many trials to run — not a reason to discard a lopsided result.
        notes.append(
            f"null control: one model against itself produced {null_floor} discordant trials, so "
            f"this arm pair's {discordant} includes that much sampling noise"
        )

    if p > alpha:
        lean = max(a_only, b_only) / discordant if discordant else 0.0
        return ArmComparison(
            arm_a,
            arm_b,
            a_only,
            b_only,
            concordant,
            p,
            None,
            TOO_CLOSE,
            discordant_needed(lean=max(lean, 0.51), alpha=alpha),
            (*notes, f"p={p:.3f} at {discordant} discordant trials"),
        )

    return ArmComparison(
        arm_a,
        arm_b,
        a_only,
        b_only,
        concordant,
        p,
        winner=arm_a if a_only > b_only else arm_b,
        notes=tuple(notes),
    )


@dataclass(frozen=True)
class ArmReport:
    """A comparison read per dimension, because the pooled number can be the wrong summary.

    Measured 2026-08-19: two models leaned in OPPOSITE directions on different dimensions and the
    pooled split cancelled to 12/9, p=0.66 — "no difference" as arithmetic, while one model swept
    five of five passes on a completeness case and the other swept three of three on grounding.

    That is this repo's canonical finding-shape, stated three times and never mechanized:
    *"The finding is the heterogeneity, not the average… A lever that helps four tasks and wrecks a
    fifth is not a fix, and shipping it on the pooled number would have been shipping a coin-flip."*
    """

    primary: str
    by_dimension: dict[str, ArmComparison]
    pooled: ArmComparison
    winner: str | None = None
    heterogeneous: bool = False

    @property
    def pooled_is_a_valid_summary(self) -> bool:
        """False when dimensions disagree in direction — then the pooled figure summarises nothing.

        Not a stylistic caveat: with opposing leans the pooled split is their difference, so it
        shrinks toward "no effect" exactly when the models differ most interestingly.
        """
        return not self.heterogeneous


def _leaning(comparison: ArmComparison) -> str | None:
    """Which arm a dimension leans toward, ignoring significance. ``None`` for a tie."""
    if comparison.a_only == comparison.b_only:
        return None
    return comparison.arm_a if comparison.a_only > comparison.b_only else comparison.arm_b


def compare_by_dimension(
    arm_a: str,
    arm_b: str,
    trials_a: dict[tuple[str, str, int], bool],
    trials_b: dict[tuple[str, str, int], bool],
    *,
    primary: str = PRIMARY_DIMENSION,
    null_floor: int | None = None,
    alpha: float = ALPHA,
) -> ArmReport:
    """Compare per dimension. Only ``primary`` may name a winner.

    Trial keys already carry the dimension, so partitioning needs no new data — the reporting was
    what pooled it. Secondary dimensions are returned with their split and p intact but their winner
    stripped, so the pre-registration is structural rather than a convention a caller may forget.
    """
    dimensions = sorted({key[1] for key in trials_a.keys() | trials_b.keys()})
    by_dimension: dict[str, ArmComparison] = {}
    for dimension in dimensions:
        subset_a = {k: v for k, v in trials_a.items() if k[1] == dimension}
        subset_b = {k: v for k, v in trials_b.items() if k[1] == dimension}
        result = compare_arms(arm_a, arm_b, subset_a, subset_b, null_floor=None, alpha=alpha)
        if dimension != primary:
            # Strip the winner rather than never computing it: the split and p stay visible as a
            # lead worth chasing, while being unusable as a claim.
            result = replace(result, winner=None, verdict=SECONDARY_NOT_DECISIVE)
        by_dimension[dimension] = result

    pooled = compare_arms(arm_a, arm_b, trials_a, trials_b, null_floor=null_floor, alpha=alpha)
    primary_result = by_dimension.get(primary)

    leans = {d: _leaning(c) for d, c in by_dimension.items()}
    directions = {lean for lean in leans.values() if lean is not None}
    return ArmReport(
        primary=primary,
        by_dimension=by_dimension,
        pooled=pooled,
        winner=primary_result.winner if primary_result else None,
        heterogeneous=len(directions) > 1,
    )
