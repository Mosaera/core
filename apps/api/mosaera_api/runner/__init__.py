"""RunSession: drive one compiled graph in a background thread.

The synchronous LangGraph ``stream``/``interrupt`` loop (the same one the CLI
drives from stdin) runs on a worker thread here. Progress lands on an event queue
(consumed by SSE), and approval-gate interrupts pause the worker until an HTTP
caller supplies a decision via ``approve``. Approvals and audit events persist to
durable memory when a store is provided.

``RunSession`` is composed from focused per-concern mixins over the shared
``RunSessionBase`` (constructor + shared state + the simple accessors/emitters):

- ``LifecycleMixin`` — start, park arm/resolve, cancel, approve, the SSE stream.
- ``BudgetMixin`` — soft/hard spend ceilings + mid-run escalation resolution.
- ``LoopMixin`` — the worker loop that drives the graph stream.
"""

from __future__ import annotations

from mosaera_api.runner._base import (
    TERMINAL_STATUSES,
    RunCancelled,
    RunSessionBase,
    RunTimeout,
)
from mosaera_api.runner._budget import BudgetMixin
from mosaera_api.runner._lifecycle import LifecycleMixin
from mosaera_api.runner._loop import LoopMixin
from mosaera_api.runner._terminal import _termination_reason

__all__ = ["TERMINAL_STATUSES", "RunCancelled", "RunSession", "RunTimeout", "_termination_reason"]


class RunSession(LifecycleMixin, BudgetMixin, LoopMixin, RunSessionBase):
    pass
