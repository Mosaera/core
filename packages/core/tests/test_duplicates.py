"""Duplicate grouping, measured against a real backlog rather than invented fixtures.

The corpus below is the live LedgerCLI backlog as of 2026-08-19, with the five duplicate groups
confirmed by hand against the repository. It is kept verbatim because a synthetic fixture would
prove only that the rule agrees with whoever wrote the fixture — and the rule this one replaces
passed its own tests while scoring ZERO on this data. The en dashes in two titles are
likewise verbatim and carry a `noqa`: normalising them would make the corpus a paraphrase.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.duplicates import duplicate_groups
from mosaera_core.spec_lint import _JACCARD_THRESHOLD, _tokens

_RAW = [
    (
        83,
        "Slice 1 – Project scaffold and add command",  # noqa: RUF001 (verbatim)
        "pyproject.toml exists in the repo root and declares zero runtime dependencies. "
        "src/budget_tracker/__init__.py is present (empty). src/budget_tracker/storage.py provides "
        "read_expenses(file_path) and write_expense(file_path, expense_dict) that handle a CSV "
        "header row. Unit tests for storage and the add command pass.",
        "in_review",
    ),
    (
        84,
        "Slice 2 – List and summary commands",  # noqa: RUF001 (verbatim)
        "`budget list` outputs all expenses in CSV format. `budget list --month=2023-08` returns "
        "only entries from August 2023. `budget summary --month=2023-08` prints total amounts per "
        "category.",
        "done",
    ),
    (
        87,
        "Fix status month handling, restore test assertion, and add empty-month test",
        "`budget status --file <tmp>.csv` with no --month reports ONLY the current calendar "
        "month's spend. tests/test_cli_limit_status.py regains a real assertion on the shape.",
        "done",
    ),
    (
        88,
        "Add a .gitignore and stop tracking build artifacts",
        "A .gitignore exists in the repo root and ignores at least: __pycache__/, *.pyc, .venv/, "
        "build/, dist/, *.egg-info/ No file under src/budget_tracker.egg-info/ remains tracked in "
        "the repository. The existing test suite still passes unchanged.",
        "deferred",
    ),
    (
        89,
        "Rewrite README with concrete usage examples for every command",
        "The README contains at least one example per command and the header is descriptive. No "
        "lint errors are reported for the README.",
        "in_review",
    ),
    (
        90,
        "Remove unused imports in test files",
        "Running `ruff` on the tests yields no F401 warnings; every imported module is used within "
        "its file.",
        "deferred",
    ),
    (
        91,
        ".gitignore creation and untracking of build artifacts",
        "After committing, `git ls-files` shows no files under src/budget_tracker.egg-info; tests "
        "pass without tracking those artifacts.",
        "deferred",
    ),
    (
        92,
        "Add CSV export built on pandas (contradictory to zero-dependencies)",
        "The code compiles and the export command works when pandas is available; pyproject.toml "
        "still declares 0 dependencies.",
        "deferred",
    ),
    (
        93,
        "Add real-time currency conversion via live API",
        "The command calls an external API and converts amounts; tests exercise this "
        "functionality.",
        "deferred",
    ),
    (
        94,
        "Rewrite README with concrete usage examples for every command per the charter",
        "",
        "deferred",
    ),
    (95, "Remove unused imports in test files", "", "deferred"),
    (96, "Add .gitignore and untrack src/budget_tracker.egg-info", "", "in_progress"),
    (
        97,
        "Add CSV export built on pandas while keeping zero-runtime-dependencies rule satisfied",
        "",
        "todo",
    ),
    (
        98,
        "Add real-time currency conversion calling a live exchange-rate API during test run",
        "",
        "todo",
    ),
    (103, "Create budget_tracker/__init__.py", "", "todo"),
    (104, "Add utils.py with ordinal helper", "", "in_review"),
]

LEDGERCLI: list[dict[str, Any]] = [
    {"id": i, "title": t, "acceptance": a, "status": s} for i, t, a, s in _RAW
]

#: Confirmed by hand against the repository: three .gitignore items, two READMEs, two
#: unused-import items, two pandas-export items, two currency-conversion items.
GROUND_TRUTH = [[88, 91, 96], [89, 94], [90, 95], [92, 97], [93, 98]]


def test_it_finds_exactly_the_real_duplicate_groups() -> None:
    """Every real group, no invented ones. Equality, not a subset check — a rule that reports
    everything would pass a containment assertion."""
    assert duplicate_groups(LEDGERCLI) == GROUND_TRUTH


def test_the_jaccard_rule_it_replaces_finds_none_of_them() -> None:
    """The measurement that justified a second similarity function, kept executable so the claim
    in `duplicates.py` cannot quietly rot into folklore.

    These duplicates are RE-CREATIONS: one side carries full acceptance criteria and the other
    carries none, so the union balloons while the intersection does not. Dividing by the union is
    structurally wrong for this shape.
    """
    fired = 0
    for group in GROUND_TRUTH:
        for pos, a in enumerate(group):
            for b in group[pos + 1 :]:
                ia = next(i for i in LEDGERCLI if i["id"] == a)
                ib = next(i for i in LEDGERCLI if i["id"] == b)
                ta = _tokens(f"{ia['title']} {ia['acceptance']}")
                tb = _tokens(f"{ib['title']} {ib['acceptance']}")
                if len(ta & tb) / len(ta | tb) >= _JACCARD_THRESHOLD:
                    fired += 1
    assert fired == 0, "the old rule now fires — re-check whether the new one is still needed"


def test_delivered_work_is_never_grouped() -> None:
    """`done` items are excluded: shipped work is not a duplicate of anything, and comparing
    against it only invents pairs — every completed slice would resurrect as a "duplicate" of the
    follow-up that built on it.

    The fixture is deliberately the HARDEST case: byte-identical titles, one delivered. Asserting
    against the LedgerCLI corpus instead would prove nothing, because its `done` items are not
    similar to anything and would stay unreported whether or not the filter existed.
    """
    twins: list[dict[str, Any]] = [
        {
            "id": 90,
            "title": "Remove unused imports in test files",
            "status": "done",
            "acceptance": "Running `ruff` on the tests yields no F401 warnings.",
        },
        {
            "id": 95,
            "title": "Remove unused imports in test files",
            "status": "deferred",
            "acceptance": "",
        },
    ]
    assert duplicate_groups(twins) == []
    # ...and the same pair, both live, IS reported — so the emptiness above is the filter at work
    # and not the rule failing to see them.
    both_live = [{**twins[0], "status": "todo"}, twins[1]]
    assert duplicate_groups(both_live) == [[90, 95]]


def test_groups_are_transitive_not_pairwise() -> None:
    """#88/#91 alone score below threshold; both reach #96. Reporting components rather than
    pairs is what recovers the whole trio — and is what an operator wants to read."""
    trio = next(g for g in duplicate_groups(LEDGERCLI) if 96 in g)
    assert trio == [88, 91, 96]


def test_a_backlog_with_nothing_alike_reports_nothing() -> None:
    """The rule must be silent by default. A detector that always finds something is noise, and
    this one advises on real projects where most items are genuinely distinct."""
    distinct: list[dict[str, Any]] = [
        {"id": 1, "title": "Add pagination to the orders API", "acceptance": "", "status": "todo"},
        {"id": 2, "title": "Upgrade the TLS certificate", "acceptance": "", "status": "todo"},
        {"id": 3, "title": "Write the onboarding runbook", "acceptance": "", "status": "todo"},
    ]
    assert duplicate_groups(distinct) == []


def test_one_item_or_none_is_not_a_comparison() -> None:
    assert duplicate_groups([]) == []
    assert duplicate_groups([{"id": 1, "title": "solo", "acceptance": "", "status": "todo"}]) == []


# --- live regression, 2026-08-19: single linkage chained on the real backlog ---------------------

_BOILERPLATE = (
    " The existing test suite still passes unchanged - this item changes no runtime behaviour."
)

#: The same corpus after item #95 was rewritten in the product — a rewrite that happened to reuse
#: #88's closing sentence. Two unrelated items therefore shared a chunk of prose, which a 16-item
#: IDF reads as rare, and the pair scored 0.305 against a 0.3 threshold.
LEDGERCLI_LIVE: list[dict[str, Any]] = [
    {**i, "acceptance": i["acceptance"] + _BOILERPLATE} if i["id"] in (88,) else dict(i)
    for i in LEDGERCLI
]
for _i in LEDGERCLI_LIVE:
    if _i["id"] == 95:
        _i["acceptance"] = (
            "Running `ruff check --select F401 tests/` reports zero findings. No import that is "
            "actually referenced anywhere in its own file has been removed." + _BOILERPLATE
        )


def test_one_shared_boilerplate_sentence_does_not_weld_two_groups() -> None:
    """The defect found in live validation, hours after shipping.

    Single linkage unions on ANY edge above the threshold, so the accidental #88-#95 edge welded
    the .gitignore items to the unused-import items into one five-item blob — and at a slightly
    lower threshold dragged in an unrelated scaffold item too. Average linkage outvotes the
    accident with the pairs that genuinely disagree.

    This is the regression that pins the linkage choice; without it, a well-meaning simplification
    back to union-find would look correct on the pre-rewrite corpus.
    """
    assert duplicate_groups(LEDGERCLI_LIVE) == GROUND_TRUTH


def test_the_grouping_is_stable_across_the_measured_threshold_band() -> None:
    """0.3 was fitted after seeing the labels, so the rule must not be balanced on it. The band
    measured on the live corpus is [0.25, 0.3]; single linkage was wrong at BOTH."""
    for threshold in (0.25, 0.3):
        assert duplicate_groups(LEDGERCLI_LIVE, threshold=threshold) == GROUND_TRUTH, threshold
