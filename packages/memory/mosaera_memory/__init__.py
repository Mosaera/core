"""Mosaera durable memory: Postgres + pgvector store for runs and their artifacts.

State that used to live only in a per-run report file is persisted here so runs
are queryable across sessions and past work is recallable by vector similarity.
"""

from mosaera_memory.models import (
    NOTE_ROLE,
    SPEAKER_ROLES,
    Approval,
    Artifact,
    AuditEvent,
    Decision,
    RepoChange,
    Run,
    TestResult,
    conversation_turns,
)
from mosaera_memory.secrets import (
    SecretKeyError,
    decrypt_secret,
    encrypt_secret,
    is_encrypted,
    secret_status,
    try_decrypt,
)
from mosaera_memory.store import EMBED_DIM, MemoryStore
from mosaera_memory.store._auth import LOGIN_BACKOFF_EXP_CAP
from mosaera_memory.store._quota import utc_day

__all__ = [
    "EMBED_DIM",
    "LOGIN_BACKOFF_EXP_CAP",
    "NOTE_ROLE",
    "SPEAKER_ROLES",
    "Approval",
    "Artifact",
    "AuditEvent",
    "Decision",
    "MemoryStore",
    "RepoChange",
    "Run",
    "SecretKeyError",
    "TestResult",
    "conversation_turns",
    "decrypt_secret",
    "encrypt_secret",
    "is_encrypted",
    "secret_status",
    "try_decrypt",
    "utc_day",
]
