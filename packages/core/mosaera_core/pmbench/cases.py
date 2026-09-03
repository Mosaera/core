"""QMB case loading — the case IS the pre-registration.

Layout follows `govbench/cases.py`, which follows `bench/cases`, so nobody learns a third
convention:

    QMB-NN/
      prompt.md      # what the operator says to Quincy
      fixture.toml   # the project he is answering ABOUT: backlog rows, repo files, brief
      case.toml      # the case class and every expectation, declared BEFORE the run

An unknown `case.toml` key RAISES, as in govbench and unlike `bench`'s silent allowlist: a typo'd
expectation that quietly does nothing is worst of all in a suite whose entire job is expectations.

The fixture is data rather than a live project on purpose. A benchmark that read the running
instance would grade a moving target, and CLAUDE.md's live-data rule exists because pointing a
test at a real store once cost ~2,500 scorecards.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_CASES_DIR = Path(__file__).parent / "cases"

#: What a case asserts about the PM. One class per RECORDED defect, so the suite begins by
#: reproducing failures this project has already paid for rather than hunting for new ones.
#:
#:   grounding    — F60 (HIGH, open, #70): the PM writes acceptance criteria without reading code.
#:   destructive  — measured 2026-08-19: proposed deleting five delivered items.
#:   consistency  — same measurement: chat and curate disagreed about the same backlog.
#:   completeness — F48's residual: asked for a cleanup, produced four locks and no cleanup.
#:   limits       — claimed "I do not have visibility into the file system" while holding a listing.
#:   no-op        — the control. The right answer is to propose NOTHING; without it a suite only
#:                  measures eagerness (govbench's G-03 plays exactly this role).
CLASSES = ("grounding", "destructive", "consistency", "completeness", "limits", "no-op")

#: Which PM entry points a case drives. "both" is what makes the consistency dimension possible.
PATHS = ("chat", "curate", "both")

_CASE_KEYS = frozenset(
    {
        "case_class",
        "paths",
        "expect_ops",
        "expect_op_kinds",
        "expect_grouped",
        "forbid_destroys",
        "must_contain",
        "must_not_contain",
        "expect_consistent",
    }
)

#: `contents` maps a path in `files` to that file's source. Added with the code-evidence change
#: (F60/#70): a fixture carrying only a LISTING cannot express the condition the grounding
#: dimension is about, so the suite could not have detected the change — the same trap the
#: evidence slice hit before fixtures gained `verdicts`. A benchmark that cannot represent what it
#: grades measures nothing, whatever its rates say.
_FIXTURE_KEYS = frozenset({"brief", "files", "item", "contents"})
_ITEM_KEYS = frozenset(
    {
        "id",
        "title",
        "description",
        "acceptance",
        "status",
        "mr_url",
        "branch",
        "position",
        # Per-criterion ledger verdicts, as `verdicts = ["satisfied", "unmeasured", …]` positionally
        # matching the acceptance lines. Added because a fixture could not previously express the
        # state the North Star's defining question is ABOUT — "does every acceptance criterion now
        # have evidence?" — so the suite could not detect a change that answers it. A benchmark that
        # cannot represent the condition it grades measures nothing, whatever its rates say.
        "verdicts",
    }
)

#: A criterion no run has evaluated. Mirrors `mosaera_core.evidence.UNMEASURED`; asserted equal by
#: test so a rename cannot leave fixtures silently describing a verdict that no longer exists.
UNMEASURED = "unmeasured"


@dataclass(frozen=True)
class QMBCase:
    """One PM case and its pre-registered expectations."""

    id: str
    prompt: str  # what the operator says
    case_class: str
    brief: str
    files: tuple[str, ...]  # the repo listing the PM is given
    items: tuple[dict[str, Any], ...]  # the backlog rows
    #: path -> source, for the files this fixture makes readable. Only paths in `files`.
    contents: tuple[tuple[str, str], ...] = ()
    paths: str = "chat"
    #: Must the proposal contain at least one op? `False` is the no-op control's whole point.
    expect_ops: bool = True
    #: At least one op of each named kind must appear. Catches "asked for X, proposed only Y".
    expect_op_kinds: tuple[str, ...] = ()
    #: Ids that must end up in one group — e.g. duplicates that should be folded together.
    expect_grouped: tuple[tuple[int, ...], ...] = ()
    #: Ids whose ROW must survive. A proposal that deletes one of these fails, whatever its reason.
    forbid_destroys: tuple[int, ...] = ()
    #: Substrings the reply must / must not contain. Used only where the fixture provably supplies
    #: the fact, so a miss is a real defect and not a difference of phrasing.
    must_contain: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()
    #: Must chat and curate agree? Only meaningful when `paths == "both"`.
    expect_consistent: bool = False
    #: Populated by the loader for error messages.
    case_dir: Path = field(default_factory=Path)

    @property
    def drives_chat(self) -> bool:
        return self.paths in ("chat", "both")

    @property
    def drives_curate(self) -> bool:
        return self.paths in ("curate", "both")


def available_pm_cases() -> list[str]:
    if not _CASES_DIR.is_dir():
        return []
    return sorted(
        p.name
        for p in _CASES_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(("_", ".")) and (p / "prompt.md").is_file()
    )


def _evidence_for(row: dict[str, Any]) -> dict[str, Any] | None:
    """`verdicts` zipped onto the acceptance lines, in the shape the PM context builder expects.

    Positional on purpose: a fixture author writes the criteria and their verdicts side by side, and
    a mismatch in length is a broken case rather than a silent partial. `None` when the fixture
    declares no verdicts, so every existing case renders exactly as before.
    """
    verdicts = row.get("verdicts")
    if not verdicts:
        return None
    lines = [ln for ln in str(row.get("acceptance") or "").splitlines() if ln.strip()]
    if len(verdicts) != len(lines):
        raise ValueError(
            f"item {row.get('id')}: {len(verdicts)} verdicts for {len(lines)} acceptance lines"
        )
    return {
        "criteria": [
            {"text": text, "verdict": str(verdict), "oracle_ref": ""}
            for text, verdict in zip(lines, verdicts, strict=True)
        ]
    }


def _load_fixture(
    case_id: str, path: Path
) -> tuple[str, tuple[str, ...], tuple[dict, ...], tuple[tuple[str, str], ...]]:
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    unknown = set(raw) - _FIXTURE_KEYS
    if unknown:
        raise ValueError(f"{case_id}: unknown fixture.toml key(s) {sorted(unknown)}")
    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in raw.get("item", []):
        bad = set(row) - _ITEM_KEYS
        if bad:
            raise ValueError(f"{case_id}: unknown item key(s) {sorted(bad)}")
        if "id" not in row:
            raise ValueError(f"{case_id}: every fixture item needs an id")
        item_id = int(row["id"])
        if item_id in seen:
            raise ValueError(f"{case_id}: duplicate fixture item id {item_id}")
        seen.add(item_id)
        items.append(
            {
                "id": item_id,
                "title": str(row.get("title", "")),
                "description": str(row.get("description", "")),
                "acceptance": str(row.get("acceptance", "")),
                "status": str(row.get("status", "todo")),
                "mr_url": str(row.get("mr_url", "")),
                "branch": str(row.get("branch", "")),
                "position": int(row.get("position", item_id)),
                # Rendered into the context exactly as the real reconciliation does, so a case
                # exercises the production renderer rather than a fixture-shaped imitation.
                "evidence": _evidence_for(row),
            }
        )
    files = tuple(raw.get("files", []))
    contents = tuple((str(k), str(v)) for k, v in (raw.get("contents") or {}).items())
    for rel, _body in contents:
        # A content entry for a path the PM is not even shown in the listing would never be
        # selected, so the case would silently grade something it never presented.
        if rel not in files:
            raise ValueError(f"{case_id}: contents names {rel!r}, which is not in files")
    return str(raw.get("brief", "")).strip(), files, tuple(items), contents


def load_pm_case(case_id: str) -> QMBCase:
    case_dir = _CASES_DIR / case_id
    prompt = case_dir / "prompt.md"
    if not prompt.is_file():
        raise ValueError(
            f"unknown PM case {case_id!r}; available: {', '.join(available_pm_cases()) or '(none)'}"
        )
    raw = tomllib.loads((case_dir / "case.toml").read_text(encoding="utf-8"))
    unknown = set(raw) - _CASE_KEYS
    if unknown:
        raise ValueError(f"{case_id}: unknown case.toml key(s) {sorted(unknown)}")

    case_class = str(raw.get("case_class", ""))
    if case_class not in CLASSES:
        raise ValueError(f"{case_id}: case_class must be one of {CLASSES}, got {case_class!r}")
    paths = str(raw.get("paths", "chat"))
    if paths not in PATHS:
        raise ValueError(f"{case_id}: paths must be one of {PATHS}, got {paths!r}")

    brief, files, items, contents = _load_fixture(case_id, case_dir / "fixture.toml")
    known = {int(i["id"]) for i in items}
    for field_name in ("forbid_destroys",):
        for item_id in raw.get(field_name, []):
            if int(item_id) not in known:
                raise ValueError(f"{case_id}: {field_name} names unknown item {item_id}")
    for group in raw.get("expect_grouped", []):
        for item_id in group:
            if int(item_id) not in known:
                raise ValueError(f"{case_id}: expect_grouped names unknown item {item_id}")

    return QMBCase(
        id=case_id,
        prompt=prompt.read_text(encoding="utf-8").strip(),
        case_class=case_class,
        brief=brief,
        files=files,
        items=items,
        contents=contents,
        paths=paths,
        expect_ops=bool(raw.get("expect_ops", True)),
        expect_op_kinds=tuple(str(k) for k in raw.get("expect_op_kinds", [])),
        expect_grouped=tuple(tuple(int(i) for i in g) for g in raw.get("expect_grouped", [])),
        forbid_destroys=tuple(int(i) for i in raw.get("forbid_destroys", [])),
        must_contain=tuple(str(s) for s in raw.get("must_contain", [])),
        must_not_contain=tuple(str(s) for s in raw.get("must_not_contain", [])),
        expect_consistent=bool(raw.get("expect_consistent", False)),
        case_dir=case_dir,
    )
