"""Governance case loading — the case IS the pre-registration.

A case declares what the system *should* do before it is ever run: which verdict the detectors must
produce, and whether an operator question is the right response. Scoring then checks reality
against that declaration. A case whose verdict disagrees with its declared class is therefore a
**broken case, not a finding** — the same discipline every measurement this week has used, made
structural rather than remembered.

Layout mirrors `bench/cases` deliberately, so nobody has to learn a second convention:

    G-NN/
      brief.md                 # the item's ACCEPTANCE text — what the system is asked to build
      case.toml                # class, expected verdicts, kind/tier
      answer.md                # the OPERATOR's reply — the thing MCB has no equivalent of
      seed/                    # optional starting repo (the discoverable + no-op classes need one)
      grader/                  # hidden acceptance suite (opt-in arm only)
      reference/               # known-good overlay (opt-in arm only)

``brief.md`` holds acceptance text rather than a whole task description because that is what the
intake detectors actually read, and writing it as a full brief would invite grading a different
string from the one production inspects.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

_CASES_DIR = Path(__file__).parent / "cases"

# What a case says the system SHOULD do. `ask` and `silent` are the two the control pair turns on.
CLASSES = ("undecidable", "discoverable", "control", "clause-settleable", "no-op-ship")

# Keys a case.toml may set. Unlike `bench`'s silent allowlist, an unknown key here RAISES — a
# typo'd expectation that quietly does nothing is worse in a suite whose whole job is expectations.
_CASE_KEYS = frozenset(
    {
        "case_class",
        "kind",
        "tier",
        "expect_checkability",
        "expect_decidability",
        "expect_reachability",
        "expect_ask",
        "clause_binds",
        "clause_value",
        "max_iterations",
    }
)


@dataclass(frozen=True)
class GovCase:
    """One governance case and its pre-registered expectations."""

    id: str
    acceptance: str  # the item's acceptance text (from brief.md)
    answer: str  # the operator's reply, applied when an ask is raised (from answer.md)
    case_class: str
    seed_dir: Path
    grader_dir: Path
    reference_dir: Path
    kind: str = "python"
    tier: str = "moderate"
    expect_checkability: str = "CHECKABLE"
    expect_decidability: str = "DECIDABLE"
    # F76/#78. Default REACHABLE so every existing case keeps its meaning; a case that expects
    # UNREACHABLE is asserting the intake check catches unbuildable work BEFORE a run starts.
    # The measurement that decides whether `intake_ask_unreachable` may ship ON is PRECISION —
    # how often a fired ask was right — because a false ask blocks legitimate work.
    expect_reachability: str = "REACHABLE"
    expect_ask: bool = False
    # For the clause-settleable class: the decision that must silence the second ask.
    clause_binds: str = ""
    clause_value: int = 0
    max_iterations: int = 6

    @property
    def has_seed(self) -> bool:
        return self.seed_dir.is_dir()

    @property
    def gradeable(self) -> bool:
        """Whether the opt-in arm can score this case (needs a grader AND a known-good overlay)."""
        return self.grader_dir.is_dir() and self.reference_dir.is_dir()


def available_gov_cases() -> list[str]:
    return sorted(
        p.name
        for p in _CASES_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(("_", ".")) and (p / "brief.md").is_file()
    )


def load_gov_case(case_id: str) -> GovCase:
    case_dir = _CASES_DIR / case_id
    brief = case_dir / "brief.md"
    if not brief.is_file():
        raise ValueError(
            f"unknown governance case {case_id!r}; available: {', '.join(available_gov_cases())}"
        )
    toml_path = case_dir / "case.toml"
    raw = tomllib.loads(toml_path.read_text(encoding="utf-8")) if toml_path.is_file() else {}
    unknown = set(raw) - _CASE_KEYS
    if unknown:
        raise ValueError(f"{case_id}: unknown case.toml key(s) {sorted(unknown)}")
    case_class = str(raw.get("case_class", ""))
    if case_class not in CLASSES:
        raise ValueError(f"{case_id}: case_class must be one of {CLASSES}, got {case_class!r}")
    answer_path = case_dir / "answer.md"
    return GovCase(
        id=case_id,
        acceptance=brief.read_text(encoding="utf-8").strip(),
        answer=answer_path.read_text(encoding="utf-8").strip() if answer_path.is_file() else "",
        seed_dir=case_dir / "seed",
        grader_dir=case_dir / "grader",
        reference_dir=case_dir / "reference",
        **{k: v for k, v in raw.items() if k != "case_class"},  # type: ignore[arg-type]
        case_class=case_class,
    )
