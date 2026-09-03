"""Shared run-machinery for the API — the ``AppContext`` god-object, relocated
out from under ``routes/`` (it owns none of the HTTP routing) and split by
concern into focused mixins.

``AppContext`` owns the mutable run state that used to live as locals inside
``create_app`` — the session table, project-run mutex, rehydration bookkeeping,
the checkpointer, and durable history — plus the ~13 helper closures that
operated over them (launch, rehydrate, budget, get-or-rehydrate, …). ``create_app``
builds ONE ``AppContext`` and binds local aliases so the still-inline endpoints
call these methods unchanged.

The concerns compose over the shared ``AppContextBase`` (state + cross-concern
helpers):

- ``SessionsMixin`` — session registry + project-run mutex.
- ``LaunchMixin`` — launch, launch_item, advance_project.
- ``RehydrateMixin`` — restart recovery for a run parked at a gate.
- ``EscalationMixin`` — live model escalation + resilient re-curate/defer.
- ``DeliveryMixin`` — MR last-mile + project budget accounting.
"""

from __future__ import annotations

from mosaera_api.app_context._base import AppContextBase, GraphFactory
from mosaera_api.app_context._delivery import DeliveryMixin
from mosaera_api.app_context._escalation import EscalationMixin
from mosaera_api.app_context._launch import LaunchMixin
from mosaera_api.app_context._rehydrate import RehydrateMixin
from mosaera_api.app_context._sessions import SessionsMixin

__all__ = ["AppContext", "GraphFactory"]


class AppContext(
    SessionsMixin,
    LaunchMixin,
    RehydrateMixin,
    EscalationMixin,
    DeliveryMixin,
    AppContextBase,
):
    pass
