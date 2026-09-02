"""The third intake axis: is this item BUILDABLE by the engine's toolset? (F76, #78)

Item 88's acceptance was perfectly checkable and perfectly decidable and could not be built — it
required untracking a git file, which no tool performs. Five runs, ~2.9M tokens, four findings, and
it then presented at the escalation gate as a TEST problem, where the natural repair (amend the
blocking test) would have laundered a capability gap into a green run.

The precision half of this file matters more than the recall half. A matcher that cries wolf gets
ignored — `spec_lint` says exactly that about PARTIALLY_CHECKABLE — and a false ask BLOCKS
legitimate work behind a question. So the corpus below is real acceptance text from items that
actually delivered, not fixtures chosen to pass.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.reachability import reachability, reachability_findings, unreachable_reason

# Item 88's acceptance, verbatim from the live instance.
_ITEM_88 = (
    "A .gitignore exists in the repo root and ignores at least: __pycache__/, *.pyc, "
    ".venv/, build/, dist/, *.egg-info/\n"
    "No file under src/budget_tracker.egg-info/ remains tracked in the repository.\n"
    "The existing test suite still passes unchanged - this item changes no runtime behaviour."
)

# LedgerCLI items 83-87 — every one of these DELIVERED, so every one must judge reachable.
_DELIVERED_CORPUS = {
    83: (
        "A pyproject.toml exists with the package configured.\n"
        "Running the CLI with no arguments prints usage and exits 0.\n"
        "A test covers the add command writing a row to the CSV."
    ),
    84: (
        "The list command prints every recorded expense, one per line.\n"
        "The summary command prints a total per category.\nBoth are covered by tests."
    ),
    85: (
        "A limit can be set per category and is persisted.\n"
        "The status command reports spend against each limit."
    ),
    86: (
        "status must scope spend to the month given, not the whole file.\n"
        "A test covers a month boundary."
    ),
    87: (
        "Fix status month handling, restore the removed test assertion, "
        "and add an empty-month case."
    ),
}


def _items(mapping: dict[int, str]) -> list[dict[str, Any]]:
    return [{"id": i, "status": "todo", "acceptance": a} for i, a in mapping.items()]


# --- the red case ------------------------------------------------------------------------------


def test_item_88_is_UNREACHABLE() -> None:
    """THE pin. This exact text passed intake five times and burned five runs."""
    assert reachability(_items({88: _ITEM_88})) == {88: "UNREACHABLE"}


def test_it_fires_on_the_untrack_criterion_and_NOT_on_the_gitignore_one() -> None:
    """Precision within a single item. Writing a `.gitignore` is ordinary buildable work; only the
    'remains tracked in the repository' line is impossible. Firing on both would tell an operator
    the whole item is unbuildable, which is false and would get the axis switched off."""
    lines = _ITEM_88.split("\n")
    assert not unreachable_reason(lines[0])  # the .gitignore criterion
    assert unreachable_reason(lines[1])  # the untrack criterion
    assert not unreachable_reason(lines[2])  # the suite-still-passes criterion


def test_the_reason_names_the_capability_and_its_evidence() -> None:
    """A refusal with no reason is the defect class this repo measured four times in one day."""
    why = unreachable_reason("No file under src/pkg.egg-info/ remains tracked in the repository.")
    assert "version-control" in why
    assert "no git tool exists" in why  # the evidence, not an opinion


def test_the_finding_tells_the_operator_what_to_DO() -> None:
    findings = reachability_findings(_items({88: _ITEM_88}))
    assert len(findings) == 1
    assert findings[0].item_id == 88
    assert findings[0].rule == "unreachable_claim"
    assert "manual step" in findings[0].detail


# --- precision: the half that decides whether this axis is usable ------------------------------


def test_every_item_that_ACTUALLY_DELIVERED_is_reachable() -> None:
    """Real text from LedgerCLI 83-87. One false positive here would block work that demonstrably
    builds, which is worse than the miss it is trying to prevent."""
    verdicts = reachability(_items(_DELIVERED_CORPUS))
    assert verdicts == dict.fromkeys(_DELIVERED_CORPUS, "REACHABLE"), verdicts


def test_it_does_not_fire_on_the_NOUN() -> None:
    """The trap a keyword list walks into. Each mentions a capability word while asking for
    ordinary buildable work — and the naive fix for item 88 (trigger on 'git') fires on the
    first one."""
    for text in (
        "The README documents the git workflow for contributors.",
        "The changelog entry is committed alongside the release.",
        "The report tracks the running total across categories.",
        "A migration file is added under migrations/ defining the new column.",
        "The install docs explain how a contributor sets the project up.",
    ):
        assert not unreachable_reason(text), text


def test_DECLARING_a_dependency_is_buildable_but_RUNNING_an_installer_is_not() -> None:
    """The distinction I got wrong on the first pass: adding a package to the manifest IS the
    supported path (the coder edits it, the install phase reads it), so firing on 'use the requests
    package' would block legitimate work. Only the ad-hoc invocation is out of capability."""
    assert not unreachable_reason("Install the requests package and use it for the HTTP client.")
    assert unreachable_reason("Run pip install requests before the tests execute.")


def test_AUTHORING_a_migration_is_buildable_but_APPLYING_one_is_not() -> None:
    assert not unreachable_reason("A migration file is added under migrations/ for the new column.")
    assert unreachable_reason("Run the migration against the development database.")


def test_a_real_rename_request_is_caught() -> None:
    assert unreachable_reason("Rename src/old_name.py to src/new_name.py across the codebase.")


# --- contract: same shape as its two siblings ---------------------------------------------------


def test_settled_items_are_not_judged() -> None:
    """todo-only, like `checkability` and `decidability`. A delivered item is not re-litigated."""
    assert reachability([{"id": 88, "status": "done", "acceptance": _ITEM_88}]) == {}


def test_an_empty_acceptance_is_reachable_not_a_crash() -> None:
    assert reachability(_items({1: ""})) == {1: "REACHABLE"}


def test_the_matcher_reads_the_SAME_inventory_the_prompt_renders() -> None:
    """The anti-drift pin, and the reason this is data rather than a regex per defect. A capability
    named in OUT_OF_CAPABILITY must reach BOTH the PM's prompt and this check — F71's lesson was a
    second origin that downstream consumers silently missed."""
    from mosaera_policies.allowlist import OUT_OF_CAPABILITY, render_capabilities

    rendered = render_capabilities({"read_file": "read a file"})
    for entry in OUT_OF_CAPABILITY:
        assert entry.phrase in rendered, f"{entry.id} is checked but never shown to the PM"
        assert entry.asks_for, f"{entry.id} can never fire"
        assert entry.because, f"{entry.id} states no evidence for why it is out of capability"


# --- the knob: inert when off, and it ships off -------------------------------------------------


def test_the_axis_raises_NO_ask_while_the_knob_is_off() -> None:
    """It ships default-OFF, so the thing to assert is that it does nothing. A knob that ships off
    and is never measured is how `disposition_gap_close` sat at zero conversions — and the verdict
    is still DERIVED for display either way, which is the posture `decidability` shipped with."""
    from mosaera_core.intake_ask import askable_items

    items = _items({88: _ITEM_88})
    assert askable_items(items, ()) == {}
    assert askable_items(items, (), reachability_asks=False) == {}
    # ...and the verdict is available regardless, so the signal is visible before it is binding.
    assert reachability(items) == {88: "UNREACHABLE"}


def test_turning_it_ON_makes_item_88_askable_on_the_reachability_axis() -> None:
    from mosaera_core.intake_ask import REACHABILITY, askable_items

    assert askable_items(_items({88: _ITEM_88}), (), reachability_asks=True) == {88: REACHABILITY}


def test_one_ask_per_item_across_all_three_axes() -> None:
    """`intake_ask`'s batching rule: "Never two questions about one item." An item that is BOTH
    under-specified and unreachable must yield exactly one axis, and the sharper question wins."""
    from mosaera_core.intake_ask import CHECKABILITY, askable_items

    vague_and_unbuildable = _items(
        {7: "It should be tidy. Nothing remains tracked in the repository."}
    )
    axes = askable_items(vague_and_unbuildable, (), decidability_asks=True, reachability_asks=True)
    assert list(axes.values()) in ([CHECKABILITY], ["reachability"]), axes
    assert len(axes) == 1


def test_the_knob_defaults_to_off_in_settings() -> None:
    """Asserted against Settings, not the Knob table, because the default that matters is the one
    the engine reads."""
    from mosaera_core.config import Settings

    assert Settings().intake_ask_unreachable is False
