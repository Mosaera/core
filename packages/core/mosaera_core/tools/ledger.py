"""The read-only history tool: Quincy asking his own project's records a question.

The FIRST tool in this repo that reads the database rather than a workspace clone, and the first
built PER REQUEST rather than per run — `project_id` is a fact about the turn, not about the
graph. `build_repo_tools` stays the sole owner of repo tools; this is a separate factory with a
separate owner (`pm_turn.pm_chat`), and saying so keeps both claims true.

ADR-0111 authorises exactly this and nothing more. The queries are fixed, the enum is closed, and
`project_id` is supplied by the server — so nothing the model reads can widen what it reads next.
There is no path argument here and no file is ever opened; repository reads in chat remain
rejected and would need their own ADR.

Why fixed queries rather than letting the model write SQL: the questions have exact answers over
a known schema, and a citable count that is occasionally wrong is worse than no count at all.
See `mosaera_core.project_memory` for the measured version of that argument.
"""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.tools import BaseTool, tool

from mosaera_core.project_memory import (
    criteria_that_failed_here,
    item_history,
    open_work_and_blockers,
    orphaned_history,
    recurring_failures,
)
from mosaera_core.project_memory_render import render_answer

#: Findings shown per answer. Higher than the standing block's 3 and the CLI's 8: reaching past
#: the block's truncation is the whole reason this tool exists.
_MAX_FINDINGS = 12

#: Hard ceiling on one answer. Deliberately well below the repo tools' 16k — this shares a
#: conversation's context window with the standing blocks and the transcript, not a fresh one.
_MAX_CHARS = 6_000

_QUERIES = ("open_work", "failures", "item_history", "criteria_failed", "orphaned")


class HistoryReader(Protocol):
    """What the tool needs from a store. A Protocol, not `MemoryStore`, so a test can hand it
    three dicts instead of a database."""

    def history_runs(self, project_id: str) -> list[dict[str, Any]]: ...

    def history_items(self, project_id: str) -> list[dict[str, Any]]: ...

    def history_run_item_ids(self, project_id: str) -> list[int]: ...


def _fence(text: str) -> str:
    """Prefix every line, so nothing in the payload can start at column 0 and forge a heading.

    The bytes here are mostly engine-written counts and ids, but not entirely: item titles and
    acceptance text are operator- and model-authored. `project_memory` flattens those at the
    origin, which stops a newline; this stops a single line that merely READS like a heading.
    Same rule as `fence_tool_output` in the agent prompts, applied here because a tool's return
    value goes into the transcript without passing through a prompt builder.
    """
    return "\n".join("| " + line for line in text.splitlines())


def build_ledger_tools(reader: HistoryReader, project_id: str) -> list[BaseTool]:
    """The ledger tools for ONE project, or `[]` if this store cannot answer history questions.

    Degrading to `[]` rather than raising is deliberate: a store one migration behind should cost
    the tool, never the conversation. With no tools the agent still builds and the turn is simply
    a single model call.
    """
    if getattr(reader, "history_runs", None) is None:
        return []

    # One read per kind per turn. The tool is per-request, so this cannot go stale across turns,
    # and five questions in one conversation cost three queries instead of fifteen.
    cache: dict[str, Any] = {}

    def _runs() -> list[dict[str, Any]]:
        if "runs" not in cache:
            cache["runs"] = reader.history_runs(project_id)
        return cache["runs"]

    def _items() -> list[dict[str, Any]]:
        if "items" not in cache:
            cache["items"] = reader.history_items(project_id)
        return cache["items"]

    @tool
    def project_history(query: str) -> str:
        """Ask this project's own records a question. Read-only; nothing here changes anything.

        query must be exactly one of:
        - open_work — which open items are blocked, and which unfinished item blocks the most
        - failures — how this project tends to fail, by recorded park cause and gate reason
        - item_history — items that took three or more runs, and how each attempt ended
        - criteria_failed — acceptance text of items whose runs died on the criterion, not the code
        - orphaned — runs whose backlog item no longer exists (holes in the record)

        Answers carry the run and item ids behind them; cite those when they matter. An empty
        answer says WHY it is empty, because "nothing is blocked" and "no dependencies were ever
        recorded" are the same empty list and opposite facts.
        """
        if query not in _QUERIES:
            return f"ERROR: unknown query {query!r}. Valid queries: {', '.join(_QUERIES)}"
        try:
            if query == "open_work":
                answer = open_work_and_blockers(_items())
            elif query == "failures":
                answer = recurring_failures(_runs())
            elif query == "item_history":
                answer = item_history(_runs(), _items())
            elif query == "criteria_failed":
                answer = criteria_that_failed_here(_runs(), _items())
            else:
                answer = orphaned_history(reader.history_run_item_ids(project_id), _items())
        except Exception as exc:
            # Clipped: a database error can carry an entire SQL statement, and the model has no
            # use for one. The API log gets the real traceback.
            return f"ERROR: this project's history could not be read: {str(exc)[:200]}"
        text = render_answer(
            answer,
            limit=_MAX_FINDINGS,
            more_hint="recorded, but not shown here — ask a narrower question",
        )
        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS] + "\n… (truncated — ask a narrower question)"
        return _fence(text)

    return [project_history]
