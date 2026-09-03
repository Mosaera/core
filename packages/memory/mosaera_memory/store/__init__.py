"""MemoryStore: the write/read API over the durable memory schema.

Schema is managed by Alembic (``mosaera_memory/migrations``): ``init()`` creates
the pgvector extension, then upgrades to head — or, for a pre-Alembic database
already carrying the full schema (from the old create_all path), stamps it at
head so no migration re-creates existing objects. Schema changes ship as new
migrations, never ad-hoc ``ALTER``s.

``MemoryStore`` composes focused per-aggregate mixins, each in its own module,
over the shared ``StoreBase`` infrastructure (engine/session + schema lifecycle).
"""

from __future__ import annotations

from mosaera_memory.store._auth import AuthMixin
from mosaera_memory.store._backlog import BacklogMixin
from mosaera_memory.store._base import EMBED_DIM
from mosaera_memory.store._charter import CharterMixin
from mosaera_memory.store._claims import ClaimsMixin
from mosaera_memory.store._clauses import ClausesMixin
from mosaera_memory.store._content import ContentMixin
from mosaera_memory.store._contracts import ContractsMixin
from mosaera_memory.store._coverage import CoverageMixin
from mosaera_memory.store._doctrine import DoctrineMixin
from mosaera_memory.store._health import HealthMixin
from mosaera_memory.store._history import HistoryMixin
from mosaera_memory.store._map import MapMixin
from mosaera_memory.store._projects import ProjectsMixin
from mosaera_memory.store._quota import QuotaMixin
from mosaera_memory.store._runs import RunsMixin
from mosaera_memory.store._sessions import SessionsMixin
from mosaera_memory.store._steps import StepsMixin

__all__ = ["EMBED_DIM", "MemoryStore"]


class MemoryStore(
    RunsMixin,
    ProjectsMixin,
    BacklogMixin,
    ContentMixin,
    StepsMixin,
    SessionsMixin,
    CoverageMixin,
    CharterMixin,
    HealthMixin,
    ClausesMixin,
    ClaimsMixin,
    ContractsMixin,
    HistoryMixin,
    MapMixin,
    QuotaMixin,
    AuthMixin,
    DoctrineMixin,
):
    pass
