"""Watch a PM turn happen, over one streamed POST.

Deliberately not the runs' machinery. That stream is an `EventSource` over a long-lived
supervised run, with a session registry, a replay backlog and reconnect semantics — and it is
GET-only, which a chat turn (a POST with a body) cannot use at all. A conversation turn lives
about ten seconds and belongs to one asker, so it streams its own response body and keeps none of
that apparatus.

**The stream is a VIEW of the work, never the work itself.** The turn runs on a thread and writes
its rows whether or not anyone is still listening, so closing the tab loses the live display and
nothing else — the transcript already has the answer on the next fetch. Anything that made the
turn depend on the reader would trade a durable record for a nicer animation.

Async generator, not sync: the repo learned on the runs endpoint that a sync generator streamed
through `iterate_in_threadpool` pins one anyio worker per open connection, and there are about
forty. Idling here holds nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from collections.abc import AsyncGenerator
from typing import Any

from mosaera_memory import MemoryStore

from mosaera_api.pm_turn import pm_chat

_log = logging.getLogger(__name__)

#: How often the drain wakes while the model is working. Short because a person is watching a
#: conversation, not supervising a run — the runs' 250ms would be visible as lag on a status line
#: that is meant to feel immediate. The turn is seconds long, so the poll costs little.
_POLL_SECONDS = 0.05

#: Internal marker that the worker finished. Never written to the wire.
_END = "_end"


def _frame(event: str, data: dict[str, Any]) -> str:
    """One SSE frame. Same wire shape as the runs stream, so anything that already reads SSE
    here reads this too — the difference between the two is the transport around it, not the
    bytes."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream_turn(
    memory: MemoryStore,
    project_id: str,
    text: str,
    attachment_ids: list[str] | None = None,
    session_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Run one turn on a thread and report it as it happens.

    Four events. `step` is a lookup starting, `text` is Quincy saying something mid-turn, `done`
    carries exactly the payload the plain endpoint returns, and `error` covers the case the turn
    itself could not handle.

    Note there is no separate `failed` event: `done`'s payload already carries `failure_cause`, so
    the client reads the outcome in one place rather than two that could disagree.

    Typed as an ASYNC GENERATOR, not an `AsyncIterator`. This `async def` yields, so a generator is
    what it is — and the difference is not cosmetic: a caller that abandons the stream mid-turn has
    to `aclose()` it to run the cleanup, and `AsyncIterator` does not carry that method. The
    abandonment test in `test_pm_stream.py` calls exactly that, which is how the mis-annotation
    surfaced.
    """
    events: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
    outcome: dict[str, Any] = {}

    def work() -> None:
        try:
            outcome["payload"] = pm_chat(
                memory,
                project_id,
                text,
                attachment_ids=attachment_ids,
                session_id=session_id,
                on_event=lambda kind, payload: events.put((kind, payload)),
            )
        except Exception as exc:
            _log.warning("streamed pm turn failed for %s: %s", project_id, exc, exc_info=True)
            outcome["error"] = str(exc)
        finally:
            # Always, on every path: a reader waiting on a queue nobody will fill again is the
            # one failure mode worse than an error frame.
            events.put((_END, {}))

    worker = threading.Thread(target=work, daemon=True, name=f"pm-turn-{project_id}")
    worker.start()

    while True:
        try:
            kind, payload = events.get_nowait()
        except queue.Empty:
            await asyncio.sleep(_POLL_SECONDS)
            continue
        if kind == _END:
            break
        yield _frame(kind, payload)

    if "payload" in outcome:
        yield _frame("done", outcome["payload"])
    else:
        # `pm_chat` handles its own failures and returns a payload for them, so reaching here
        # means something outside that contract broke. Say so rather than closing silently.
        yield _frame("error", {"detail": outcome.get("error", "the turn ended unexpectedly")})
