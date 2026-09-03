"""Lifecycle concern: start the worker, arm/resolve approval parks, cancel,
approve, and the SSE event stream.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

from mosaera_api.runner._base import _CANCELLED, TERMINAL_STATUSES, RunSessionBase
from mosaera_api.runner._summaries import persist_agent_summaries

# aevents() poll cadences. The worker flips status terminal BEFORE emitting the final done/_end
# events, so once we see terminal+empty we poll a short GRACE (fast, bounded) to let them land
# rather than returning immediately and dropping them — then give up so a finished stream can't
# hang. _TERMINAL_GRACE_POLLS * _TERMINAL_GRACE_INTERVAL ~= 2s covers the inter-emit DB writes.
_ASYNC_POLL_INTERVAL = 0.25
_TERMINAL_GRACE_INTERVAL = 0.05
_TERMINAL_GRACE_POLLS = 10  # ~0.5s: covers the ms-scale status→done→_end DB writes with margin

# D4: an awaiting_approval park is exactly where a human deliberates longest — and exactly
# where the connection sends nothing for that whole stretch, the one shape an idle proxy/NAT
# timeout is most likely to kill silently (uvicorn's own keep-alive timeout only applies
# between requests, not mid-stream, so this is squarely an intermediary/browser risk, not the
# app server). A synthetic `_ping` every ~15s keeps bytes flowing without adding a real event to
# the transcript; the SSE route renders it as a bare comment line so EventSource never dispatches
# it. Idle-only: any real event resets the counter, so a busy run never emits one.
_HEARTBEAT_IDLE_POLLS = 60  # 60 * _ASYNC_POLL_INTERVAL ~= 15s of silence


class LifecycleMixin(RunSessionBase):
    def start(self) -> None:
        self.status = "running"
        self.started_at = time.time()
        # Create the parent run row up front so mid-run approvals/audit events
        # satisfy the foreign key before the final record_run upsert at delivery.
        if self._memory is not None:
            # initial is None for a rehydrated (resume) session — its row and
            # checkpoint already exist; streaming None replays to the interrupt.
            task = (self._initial or {}).get("task", "")
            self._safe(lambda: self._memory.ensure_run(self.run_id, task=task))
            if self._project_id or self._item_id:
                self._safe(
                    lambda: self._memory.tag_run(self.run_id, self._project_id, self._item_id)
                )
        self._audit("run.started")
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"run-{self.run_id}")
        self._thread.start()

    def _enter_awaiting(self, interrupt: dict[str, Any]) -> None:
        """Arm a park: publish the interrupt, flip to awaiting_approval, and mark
        the one decision slot open — all atomically, so a concurrent approve()/
        cancel() observes a consistent state and exactly one claims it."""
        with self._decision_lock:
            self.pending_interrupt = interrupt
            self.status = "awaiting_approval"
            self._awaiting_decision = True
        # Durably checkpoint spend-so-far OUTSIDE the lock: the worker blocks at a park
        # and a restart can kill it before its terminal `finally` ever runs, so this is
        # the only cost record until the run resumes. Newest cost row wins on read, so
        # re-parking / finalizing simply supersedes it. Reseeded on rehydrate.
        self._persist_cost()
        persist_agent_summaries(self)

    def cancel(self) -> None:
        """Signal the worker to stop at its next checkpoint.

        Non-blocking: the worker owns the terminal 'cancelled' transition;
        until then the session reads 'cancelling'. The durable CANCELLED row
        is the caller's job (history.cancel_run) — the worker never persists
        a cancelled run.
        """
        self._cancel.set()
        with self._decision_lock:
            if self.status in ("pending", "running", "awaiting_approval"):
                self.status = "cancelling"
            # Close the decision slot so a racing approve() is rejected.
            self._awaiting_decision = False
            try:
                # Unpark a gate-parked worker. put_nowait: _resume has maxsize=1
                # and a racing approve() must never deadlock the HTTP thread —
                # if a decision is already queued, the cancel event is seen at
                # the next checkpoint instead.
                self._resume.put_nowait(_CANCELLED)
            except queue.Full:
                pass

    def approve(
        self,
        approved: bool,
        feedback: str = "",
        authorize_tests: list[str] | None = None,
        option_id: str | None = None,
    ) -> None:
        """Resolve the pending park. Raises ``RuntimeError`` when nothing is awaiting (409) and
        ``ValueError`` for an `option_id` this gate did not offer (400) — never a silent pass."""
        with self._decision_lock:
            # Claim the single decision slot: a second concurrent approve (or one
            # arriving after cancel/worker-resume) sees the slot closed and is
            # rejected, so its decision can never leak into a later park.
            if self.status != "awaiting_approval" or not self._awaiting_decision:
                raise RuntimeError("run is not awaiting approval")
            action = ""
            outcomes: list[dict[str, Any]] = []
            if self.pending_interrupt:
                value = self.pending_interrupt.get("value")
                if isinstance(value, dict):
                    action = str(value.get("action", ""))
                    outcomes = [
                        o
                        for o in (value.get("outcomes") or [])
                        if isinstance(o, dict) and o.get("id")
                    ]
            offered: list[str] = [str(o.get("id")) for o in outcomes]
            # Validated INSIDE the lock and BEFORE the slot is claimed: a rejected option must
            # leave the park answerable, or a typo would strand the run with nothing awaiting.
            if option_id is not None and option_id not in offered:
                raise ValueError(
                    f"unknown option {option_id!r} for this gate"
                    + (f" — it offers {', '.join(offered)}" if offered else " (it offers none)")
                )
            # The EFFECT the gate itself computed for the option the operator picked — resolved
            # here, from the offered set this same call just validated against, so presentation and
            # routing cannot drift (the `deny_finalizes` idiom, applied to the resume).
            #
            # Before this, `option_id` was recorded and discarded, and every option collapsed to
            # `(approve, feedback)`. `stop_honestly` and `send_back` are BOTH `approve=False` with
            # whatever is in the notes box, so they were byte-identical to the engine — and
            # `_supervise` had to guess intent from whether feedback was empty. It guessed wrong in
            # the one case that matters: an escalation the run CAN continue from is exactly where
            # `stop_honestly` is the operator's only way to stop, and typing a note made it
            # re-scope instead. F61's shape inside F61's own fix, found by audit 2026-08-21.
            effect = next(
                (str(o.get("effect", "")) for o in outcomes if str(o.get("id")) == option_id),
                "",
            )
            self._awaiting_decision = False
            try:
                # Exactly one claimer per park and the queue is drained each park,
                # so this never blocks; Full only if a cancel already queued.
                self._resume.put_nowait(
                    {
                        "approve": approved,
                        "feedback": feedback,
                        "authorize_tests": list(authorize_tests or []),
                        # Carried for the record: `option_id` is what the operator BELIEVED they
                        # chose. `parse_decision` still ignores both extras — the delivery gate
                        # routes on approve/feedback exactly as before.
                        "option_id": option_id,
                        # ...but `effect` DOES steer, at the supervise escalation. It is the
                        # gate's own computed verb for this option, not a second reading of the
                        # operator's intent, so the sentence they were shown and the branch the
                        # engine takes have one origin. Empty when no option was chosen (a legacy
                        # client, or a park that offers none) — every such caller keeps the old
                        # approve/feedback behaviour untouched.
                        "effect": effect,
                    }
                )
            except queue.Full as exc:
                raise RuntimeError("run is being cancelled") from exc
        if self._memory is not None:
            # The chosen option rides the durable approval row: "what was this person told
            # their answer would do" is the fact F61 needed and nobody could reconstruct.
            note = f"[{option_id}] {feedback}".strip() if option_id else feedback
            self._safe(lambda: self._memory.add_approval(self.run_id, action, approved, note))

    def _subscribe(self, after: int = 0) -> queue.Queue[dict[str, Any]]:
        """Register an INDEPENDENT subscriber queue seeded with the replay backlog, so every
        FRESH viewer (a new tab, a first connect) gets the full stream from the start.

        ``after`` (a stream cursor `sid` from ``_emit``, D4) replays only what came AFTER it —
        the SSE route passes the browser's own `Last-Event-ID` here on an automatic reconnect, so
        a dropped-and-resumed connection picks up where it left off instead of re-delivering the
        whole history into a transcript that never resets on a same-generator resubscribe.
        """
        sub: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._events_lock:
            for event in self._history:
                if event.get("sid", 0) > after:
                    sub.put(event)
            self._subscribers.append(sub)
        return sub

    def _unsubscribe(self, sub: queue.Queue[dict[str, Any]]) -> None:
        with self._events_lock:
            if sub in self._subscribers:
                self._subscribers.remove(sub)

    def _stream_ended(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def events(self, after: int = 0) -> Iterator[dict[str, Any]]:
        """Yield events until the run ends (SYNC, for tests that drain the replay backlog).

        Polls with a timeout instead of blocking forever so the stream ends once the run is
        finished and nothing is queued — otherwise a completed (or late) connection would hang
        open. The SSE endpoint uses ``aevents`` instead (see there).
        """
        sub = self._subscribe(after)
        try:
            while True:
                try:
                    event = sub.get(timeout=1.0)
                except queue.Empty:
                    if self._stream_ended():
                        return
                    continue
                if event["type"] == "_end":
                    return
                yield event
        finally:
            self._unsubscribe(sub)

    async def aevents(self, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Async counterpart of ``events`` for the SSE endpoint. Same replay-then-live, fan-out
        semantics, but polls the thread-safe queue NON-blockingly and ``await``s between polls,
        so an idle stream holds NO anyio threadpool token.

        The sync ``events`` run via ``iterate_in_threadpool`` pinned one worker per connection
        (blocked in ``queue.get``) for the life of the stream. anyio's threadpool defaults to 40
        tokens, so ~40 idle viewers exhausted it and starved every sync route. Awaiting an
        ``asyncio.sleep`` between non-blocking polls yields to the event loop and holds nothing.

        Terminal handling mirrors the sync path's implicit 1s grace: the worker sets the status
        terminal BEFORE emitting the final ``done``/``_end`` (with DB writes in between), so we
        must NOT bail the instant we see terminal+empty — that would drop the terminal event and
        make the client reconnect and duplicate the transcript. We poll a short bounded grace to
        let them arrive, then give up so a genuinely-finished stream still can't hang.

        ``after`` (D4): replay only backlog after this cursor — see ``_subscribe``. Also emits a
        synthetic ``_ping`` after ``_HEARTBEAT_IDLE_POLLS`` of silence (park included) so an idle
        intermediary doesn't kill the connection; the route renders it as a comment, never a
        dispatched client event, and it carries no ``sid`` so it can never become a resume cursor.
        """
        sub = self._subscribe(after)
        grace = _TERMINAL_GRACE_POLLS
        idle = 0
        try:
            while True:
                try:
                    event = sub.get_nowait()
                except queue.Empty:
                    if self._stream_ended():
                        if grace <= 0:
                            return  # run done, terminal events drained (or never coming)
                        grace -= 1
                        await asyncio.sleep(_TERMINAL_GRACE_INTERVAL)
                    else:
                        idle += 1
                        if idle >= _HEARTBEAT_IDLE_POLLS:
                            idle = 0
                            yield {"type": "_ping", "data": {}}
                        await asyncio.sleep(_ASYNC_POLL_INTERVAL)
                    continue
                if event["type"] == "_end":
                    return
                grace = _TERMINAL_GRACE_POLLS  # a delivered event resets the terminal grace
                idle = 0
                yield event
        finally:
            self._unsubscribe(sub)
