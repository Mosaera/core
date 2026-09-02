"""Shared run-time context builder (#26) — deterministic read-back of the project
brief, backlog, and what earlier items already built. Pure/offline: no DB, no models."""

from __future__ import annotations

from typing import Any

from mosaera_core.run_context import build_run_context


class _FakeMem:
    def __init__(
        self,
        items: list[dict[str, Any]],
        history: list[dict[str, Any]],
        doctrine: list[dict[str, Any]] | None = None,
    ) -> None:
        self._items = items
        self._history = history
        self._doctrine = doctrine or []

    def list_backlog_items(self, project_id: str) -> list[dict[str, Any]]:
        return self._items

    def project_history(self, project_id: str, limit: int = 8) -> list[dict[str, Any]]:
        return self._history[:limit]

    def load_doctrine(
        self, scope: str, project_id: str | None = None, kind: str | None = None
    ) -> list[dict[str, Any]]:
        return self._doctrine if scope == "project" else []


def test_ad_hoc_run_has_no_project_context() -> None:
    # No project / no memory → empty (or just the brief when one is given).
    assert build_run_context(None, None, None, "") == ""
    brief_only = build_run_context(None, None, None, "make the failing test pass")
    assert "Project brief" in brief_only and "failing test" in brief_only


def test_context_includes_brief_siblings_and_prior_work() -> None:
    items = [
        {"id": 1, "title": "Add login", "status": "done", "acceptance": "user can log in"},
        {"id": 2, "title": "Add logout", "status": "in_progress", "acceptance": "user can log out"},
    ]
    history = [
        {
            "item_id": 1,
            "title": "Add login",
            "summary": "SUMMARY: added AuthService and wired the login route",
            "files": ["auth/service.py", "auth/routes.py"],
        }
    ]
    ctx = build_run_context(_FakeMem(items, history), "proj-x", 2, "Build authentication")

    assert "Project brief" in ctx and "Build authentication" in ctx
    assert "Add login" in ctx and "Add logout" in ctx
    assert "← THIS ITEM" in ctx  # the current item is marked in the backlog block
    # What was already built is surfaced so the coder reuses it, not duplicates it.
    assert "auth/service.py" in ctx and "added AuthService" in ctx
    # The "SUMMARY:" prefix is stripped for readability.
    assert "SUMMARY:" not in ctx


def test_current_item_excluded_from_already_built() -> None:
    # A re-run of the current item must not describe the current item back to itself.
    history = [
        {"item_id": 2, "title": "Add logout", "summary": "did logout", "files": ["auth/out.py"]},
        {"item_id": 1, "title": "Add login", "summary": "did login", "files": ["auth/in.py"]},
    ]
    ctx = build_run_context(_FakeMem([], history), "proj-x", 2, "")
    assert "did login" in ctx and "auth/in.py" in ctx
    assert "did logout" not in ctx and "auth/out.py" not in ctx


def test_project_doctrine_reaches_context() -> None:
    # Per-project reference material the PM should FOLLOW is injected as a trusted block.
    doctrine = [
        {
            "source": "team-standards.md",
            "kind": "reference",
            "content": "Always validate inputs at the boundary.",
        }
    ]
    ctx = build_run_context(_FakeMem([], [], doctrine), "proj-x", 1, "Build it")
    assert "Project doctrine (trusted reference" in ctx
    assert "team-standards.md" in ctx
    assert "validate inputs at the boundary" in ctx


def test_context_respects_the_char_budget() -> None:
    big = "x" * 50_000
    items = [
        {"id": i, "title": f"item {i}", "status": "todo", "acceptance": big} for i in range(100)
    ]
    ctx = build_run_context(_FakeMem(items, []), "proj-x", 1, big, budget=3_000)
    assert len(ctx) <= 3_060  # budget + the short truncation note
    assert "truncated" in ctx
