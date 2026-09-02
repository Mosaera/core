"""What SHAPE is this repo, and can anything independently vouch for work done in it? (#121)

The onboarding flow's deterministic half. A newcomer's project is almost always greenfield — the
regime the corpus measures worst — and its DEFAULT terminal state is a park: ``evaluate_oracle``
(``graph/_oracle_legs``) needs one of four independence legs to vouch, and on a fresh repo
``standing_suite`` is empty, ``test_cmd`` is unset and the Proctor is off by default. So the OR is
false and the run stops on ``oracle_unverified`` with a green suite sitting right there. That fact
lived in the owner's head; this module is what lets the product say it BEFORE the first run.

**It measures, it does not guess.** Two things it deliberately does NOT claim:

- *"the suite passes"* — that requires EXECUTING it, which is recon's ``tests`` dimension
  (``run_coverage``, in a sandbox). Nothing here runs anything.
- *"there are tests"* from a filename. ``recon/tests.py`` names counting ``test_*`` files as the
  wrong measure, and ``standing_suite_is_independent_oracle`` already encodes the right one: a
  suite counts only when real test files exist AND some running test asserts something real. This
  reuses that second predicate rather than inventing a looser one, so what onboarding PROMISES and
  what the gate later ACCEPTS are the same question asked twice.

Pure apart from reading the clone: no sandbox, no model, no settings lookup, no writes. It runs on
the interactive path (Deterministic-First), so the walk is the bounded, symlink-safe ``recon/_fs``
one — the clone is untrusted repo content like any other (ADR-0033).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mosaera_core.graph._oracle_legs import LEG_NAMES

if TYPE_CHECKING:  # runtime import would cycle: validation imports tools.repo primitives
    from mosaera_core.tools.repo import Workspace

# The shapes, ordered from "nothing to work with" to "a suite already vouches".
#
#   empty             no source files at all — a repo that was just initialized.
#   greenfield        sources exist, no test files at all.
#   sources_no_suite  test FILES exist, but none of them asserts anything real, so no suite can
#                     act as the oracle. Kept distinct from `greenfield` because the remedy reads
#                     differently to an operator ("your tests don't assert" ≠ "you have no tests").
#   standing_suite    real test files that assert real behaviour — the `standing_suite` leg has
#                     something to work with.
SHAPES: tuple[str, ...] = ("empty", "greenfield", "sources_no_suite", "standing_suite")

# The shapes on which NO pre-existing suite can vouch, so the operator must supply independence
# some other way. `oracle_plan` recommends the Proctor exactly here.
_NEEDS_AN_ORACLE: frozenset[str] = frozenset({"empty", "greenfield", "sources_no_suite"})


@dataclass(frozen=True)
class RepoShape:
    """What the clone actually contains, with the evidence for saying so.

    ``evidence`` follows the map's provenance discipline (ADR-0047 §1): every line names where the
    statement came from, so an operator can check it. It is DATA about the repo — never instruction.
    """

    shape: str  # one of SHAPES
    source_files: int
    test_files: int
    #: The planner's own verdict on what an automated check here would be WORTH — "suite" |
    #: "shallow" | "none" | "unknown" (``ValidationPlan.strength``, declared by the LanguagePack).
    plan_strength: str
    #: The planner's human-readable reason, verbatim. Its honesty is already load-bearing.
    plan_reason: str
    project_type: str
    #: True when the walk hit its file ceiling: everything here describes a PREFIX of the repo.
    truncated: bool
    evidence: tuple[str, ...] = ()

    @property
    def needs_an_oracle(self) -> bool:
        """No pre-existing suite can act as the independent oracle for this repo."""
        return self.shape in _NEEDS_AN_ORACLE

    def as_dict(self) -> dict[str, object]:
        return {
            "shape": self.shape,
            "source_files": self.source_files,
            "test_files": self.test_files,
            "plan_strength": self.plan_strength,
            "plan_reason": self.plan_reason,
            "project_type": self.project_type,
            "truncated": self.truncated,
            "needs_an_oracle": self.needs_an_oracle,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class OraclePlan:
    """Which independence legs could vouch for this project AS CONFIGURED, and what to flip.

    ``legs`` is keyed by the SAME names ``evaluate_oracle`` records, imported from that module — so
    "what onboarding said would vouch" and "what the gate recorded as vouching" cannot drift into
    two vocabularies. A leg is True here when it COULD supply independence given the repo and the
    current configuration; it is never a prediction that the run will pass.
    """

    legs: dict[str, bool]
    #: Knob fields the operator could turn on to gain independence. Real ``GENERAL_KNOBS`` field
    #: names — the UI writes them through ``coerce_general_patch``, never a private string.
    recommended_knobs: tuple[str, ...]
    #: True when a test command would supply independence and none is set.
    recommend_test_cmd: bool

    @property
    def verified_possible(self) -> bool:
        """Some leg can vouch. False means: as configured, every run of this project parks on
        ``oracle_unverified`` no matter how good the delivered code is."""
        return any(self.legs.values())

    def as_dict(self) -> dict[str, object]:
        return {
            "legs": dict(self.legs),
            "verified_possible": self.verified_possible,
            "recommended_knobs": list(self.recommended_knobs),
            "recommend_test_cmd": self.recommend_test_cmd,
        }


def classify_repo_shape(workspace: Workspace) -> RepoShape:
    """Classify the clone. Deterministic: same tree in, same shape out."""
    from mosaera_core.recon import _fs
    from mosaera_core.testintegrity import is_collection_control, is_test_file
    from mosaera_core.validation import detect_validation_plan

    walked = _fs.walk(workspace.root)
    files = [f for f in walked.files if not is_collection_control(f)]
    test_files = [f for f in files if is_test_file(f)]
    source_files = [f for f in files if not is_test_file(f)]

    # The planner is the one component that already knows how to read a repo's language and say
    # what a check here would be WORTH. Never re-derive that from extensions.
    plan = detect_validation_plan(workspace, install=False)

    shape = _shape_of(workspace, source_files, test_files)
    evidence = _evidence_for(shape, source_files, test_files, plan.reason, walked.truncated)
    return RepoShape(
        shape=shape,
        source_files=len(source_files),
        test_files=len(test_files),
        plan_strength=plan.strength,
        plan_reason=plan.reason,
        project_type=plan.project_type,
        truncated=walked.truncated,
        evidence=evidence,
    )


def _shape_of(workspace: Workspace, source_files: list[str], test_files: list[str]) -> str:
    from mosaera_core.oraclecheck import authored_suite_asserts_behaviour

    if not source_files and not test_files:
        return "empty"
    if not test_files:
        return "greenfield"
    # Test FILES are not a suite. This is `standing_suite_is_independent_oracle`'s requirement 2,
    # asked here so the operator learns it at setup instead of at the gate. `None` (nothing
    # parseable) is NOT credited — deny-by-default, the same direction that predicate errs in.
    if authored_suite_asserts_behaviour(workspace, test_files) is True:
        return "standing_suite"
    return "sources_no_suite"


def _evidence_for(
    shape: str,
    source_files: list[str],
    test_files: list[str],
    plan_reason: str,
    truncated: bool,
) -> tuple[str, ...]:
    """Provenanced lines backing the classification. Each says where it came from."""
    lines = [
        f"{len(source_files)} source file(s) and {len(test_files)} test file(s) (tool:walk)",
        f"validation planner: {plan_reason} (tool:detect_validation_plan)",
    ]
    if shape == "sources_no_suite":
        lines.append(
            "no running test asserts a real property, so the existing tests cannot act as an "
            "independent oracle (tool:authored_suite_asserts_behaviour)"
        )
    elif shape == "standing_suite":
        lines.append(
            "at least one running test asserts a real property "
            "(tool:authored_suite_asserts_behaviour)"
        )
    if truncated:
        # ADR-0035: a partial read says so rather than reading as a complete one.
        lines.append("the file walk hit its ceiling — this describes a PREFIX of the repo")
    return tuple(lines)


def oracle_plan(shape: RepoShape, *, tester_enabled: bool, test_cmd: str) -> OraclePlan:
    """Which legs can vouch for ``shape`` given the current configuration.

    Mirrors ``evaluate_oracle``'s disjunction, one leg at a time, and deliberately answers only the
    part that is knowable BEFORE a run:

    - ``tester_vouched`` — the Proctor authors the asserting acceptance test, so it can vouch on
      any repo whenever ``tester_enabled`` is on.
    - ``standing_suite`` — only where a real, asserting suite already exists.
    - ``test_cmd`` — the operator named the command that decides the run; ``resolve_plan`` treats
      that judgement as ``strength="suite"``.
    - ``structural_vouch`` — earned per-item from a refactor/AST contract, so it cannot be promised
      from the repo alone. Always False here: claiming it would be exactly the aspirational
      statement the instrument-trust rule forbids.
    """
    can_vouch = {
        "tester_vouched": bool(tester_enabled),
        "standing_suite": shape.shape == "standing_suite",
        "test_cmd": bool(test_cmd.strip()),
        "structural_vouch": False,
    }
    # Projected THROUGH the gate's own list, so the names cannot be a second vocabulary: a route
    # added to `evaluate_oracle` and not here raises at the first call rather than silently
    # dropping a leg from what the operator is told. `test_legs_use_the_gates_own_names` pins the
    # other direction (an extra key here that the gate does not evaluate).
    legs = {name: can_vouch[name] for name in LEG_NAMES}

    stuck = not any(legs.values())
    return OraclePlan(
        legs=legs,
        # The Proctor is the leg that works on ANY repo, which is why it is the recommendation when
        # nothing else can vouch — and on a repo that already has an asserting suite it is not
        # needed, so it is not pushed.
        recommended_knobs=("tester_enabled",) if stuck and shape.needs_an_oracle else (),
        recommend_test_cmd=stuck,
    )
