"""The PM chat may read its own ledgers, and nothing else.

ADR-0111 splits the chat's reads in two: ledger queries over the project's own records are
allowed, repository reads are not and would need their own ADR. That split is only worth the
paper it is written on if something enforces it — this is the something. `scoped_tools` filters
on tool NAME against a per-role frozenset, deny-by-default, so a role naming exactly one tool can
never receive a second one even if handed the whole toolset.
"""

from __future__ import annotations

from typing import Any, cast

from mosaera_policies import GATED_ACTIONS, scoped_tools
from mosaera_policies.allowlist import ROLE_TOOL_ALLOWLIST


class _Tool:
    """Only `.name` matters to `scoped_tools`, so a stub keeps this test free of langchain."""

    def __init__(self, name: str) -> None:
        self.name = name


def test_the_chat_role_names_only_the_ledger_tool() -> None:
    assert ROLE_TOOL_ALLOWLIST["pm_chat"] == frozenset({"project_history"})


def test_the_chat_can_never_receive_a_repository_tool() -> None:
    """The invariant, not today's contents: stated as a property so a careless widening fails
    with an explanation rather than a diff nobody reads."""
    repo_tools = {"read_file", "search", "list_files"}
    assert ROLE_TOOL_ALLOWLIST["pm_chat"].isdisjoint(repo_tools | GATED_ACTIONS)


def test_scoping_drops_everything_but_the_ledger_tool() -> None:
    """Hand it the whole toolset; it keeps one. This is the mechanical half of ADR-0111 §2."""
    offered = [
        _Tool(n) for n in ("read_file", "search", "list_files", "write_file", "project_history")
    ]
    # `_Tool` carries only `.name`, deliberately: this asserts that scoping filters BY NAME and
    # nothing else, so a double that satisfied the real `BaseTool` bound would prove less.
    assert [t.name for t in scoped_tools("pm_chat", cast(Any, offered))] == ["project_history"]


def test_the_planner_does_not_inherit_the_ledger_tool() -> None:
    """The separation cuts both ways: the planner has no use for it, and a role that quietly
    accumulates capability is how an allowlist stops meaning anything."""
    assert "project_history" not in ROLE_TOOL_ALLOWLIST["pm"]


def test_the_chat_role_exercises_no_authority() -> None:
    """ADR-0105: the chat path has no actor, so it must never hold a gated action. Reaffirmed
    here rather than assumed, because this is the file where that would silently change."""
    assert ROLE_TOOL_ALLOWLIST["pm_chat"].isdisjoint(GATED_ACTIONS)
