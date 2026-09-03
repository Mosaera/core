"""Auth-surface ORM models: user accounts, login sessions, and the first-run setup gate.

Split out of ``models.py`` (which was at the modularity ceiling) but part of the SAME
declarative ``Base`` — ``models.py`` re-exports these at its bottom, so importers keep using
``from mosaera_memory.models import User`` unchanged and ``Base.metadata`` stays complete.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mosaera_memory.models import Base, _utcnow


class User(Base):
    """A human account for the self-hosted instance (capped at a small team — the
    cap is enforced in the store, not the schema). ``password_hash`` is an opaque
    string produced by the API's hasher; the raw password is never stored or logged."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    """A server-side login session backing an HttpOnly cookie. Only the SHA-256 of
    the session token is stored, so a DB leak can't be replayed as a live session.
    Deleting the row (logout / kick / expiry sweep) revokes access immediately."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class ApiKey(Base):
    """A long-lived, revocable credential issued to a user for headless callers (ADR-0127).

    Mirrors `UserSession` where the reasoning is identical -- only the SHA-256 of the key is
    stored, so a DB leak cannot be replayed -- and diverges in three places, each on purpose:

    - **No expiry.** A session times out because a browser walked away; a CI job does not. The
      operator revokes when they mean to, which is why `revoked_at` exists.
    - **Revocation is a SOFT delete.** `audit_events.run_id` is a non-nullable FK to `runs.id`,
      so there is no non-run audit channel and issuance cannot be logged there without inventing
      a synthetic run. This row therefore IS the audit record, and hard-deleting it would destroy
      the history of a credential that once had access (*Capability through Auditability*).
    - **`last_used_at` is coarse**, written only when it is already stale, so authenticating does
      not cost a database write per request.

    The key AUTHENTICATES and is never ADMIN, even when its owner is: authentication sets no
    session user, so `current_user()` stays None and `_require_admin_ctx` falls through to the
    service tier. That is how ADR-0004's "the token is not admin" stays true for this credential.
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    user: Mapped[User] = relationship(back_populates="api_keys")


class SetupToken(Base):
    """The single-row first-run setup gate (ADR-0040) — RETIRED, and deliberately still here.

    Nothing reads or writes this table any more: ADR-0116 moved first-run setup into a terminal,
    so there is no unauthenticated endpoint to gate and the token it held is gone with it. The
    TABLE stays because dropping it is a destructive migration bought against a rollback we might
    still want while the terminal wizard is young, and an empty table costs nothing. It held only
    SHA-256 hashes of one-time tokens, so there is no data here worth preserving either way.

    Drop it — migration and all — once the fresh-machine install has been done by someone who is
    not the author.
    """

    __tablename__ = "setup_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1 — single row
    token_hash: Mapped[str] = mapped_column(String(64))  # sha256 hex; plaintext never stored
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthState(Base):
    """One in-flight OAuth "Connect" handshake (ADR-0104). Holds ONLY the SHA-256 of a random
    ``state`` (plaintext never stored — same discipline as ``UserSession``/``SetupToken`` above),
    is **single-use** (the callback spends it with an atomic ``DELETE ... RETURNING``), carries a
    short TTL, and is **bound** to the initiating admin + the selected project + the provider. That
    binding is both the CSRF defense and the authorization: the callback can only ever provision the
    project the admin selected, for that admin. Nothing here is a durable credential — the OAuth
    grant is discarded after the project token is minted, so there is no per-user token table.

    ``user_id`` FKs ``users`` (CASCADE): a deleted admin's in-flight handshakes die with them.
    ``project_id`` is the project's string id by value (no FK) — a state is ephemeral and the
    callback re-validates the project exists, so a dangling row after a project delete just fails
    safe (single-use + TTL sweep it)."""

    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginBackoff(Base):
    """One login-backoff bucket: how many attempts a subject has spent, and when it last spent one
    (issue #38, ADR-0051). Durable, so backoff survives a restart and is exact across workers.

    Three shape choices, each load-bearing:

    - **``subject_hash`` keys the SUBMITTED username, not a ``users.id``.** Unknown usernames must
      back off *identically* to real ones, or the ``429`` itself becomes a username-enumeration
      oracle — a cleaner one than the timing leak ADR-0051 closes. So there is deliberately no FK:
      most subjects never correspond to a row in ``users`` at all.
    - **It is HASHED.** A durable table of submitted usernames would capture the passwords users
      periodically type into the username box. Hashing removes that entirely, and matches the
      standing discipline here — ``UserSession`` and ``SetupToken`` above store only SHA-256 too.
      The API owns the derivation (``login_subject``); ``memory`` stays a leaf that counts.
    - **``attempts`` counts ADMITTED attempts, cleared on success — not failures.** Counting
      failures would mean incrementing *after* verification, and verification is ~130ms of scrypt:
      that read-then-write window lets N concurrent requests all observe "under the threshold" and
      all guess, bounding rounds rather than guesses (the race ADR-0050 §5 rejects for the quota).
      The slot is therefore claimed BEFORE the password is checked.
    """

    __tablename__ = "login_backoff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # sha256 hex of the normalized submitted username. The normalization is coupled to
    # AuthMixin.get_user_credentials' (``.strip()``, case-SENSITIVE) and MUST change with it:
    # a coarser key (e.g. casefold) merges the distinct accounts `admin` and `Admin` into one
    # bucket, and since a success DELETES the bucket, whoever holds one clears the other's
    # counter at will — a complete bypass. See ADR-0051.
    subject_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # One bucket per subject — the conflict target the atomic claim UPSERTs against.
    __table_args__ = (UniqueConstraint("subject_hash", name="uq_login_backoff_subject"),)
