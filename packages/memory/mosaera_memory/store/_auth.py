"""Users + sessions (multi-user login) + the login-backoff throttle (#38)."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import sqlalchemy as sa
from sqlalchemy import delete, func, select, text

if TYPE_CHECKING:
    from sqlalchemy import CursorResult
from sqlalchemy.dialects.postgresql import insert as pg_insert

from mosaera_memory.models import ApiKey, User, UserSession

# Imported from its defining module rather than through ``models``' bottom re-export block: that
# block exists so PRE-EXISTING importers can keep saying ``from ...models import User``, and
# ``models`` sits one line under the 500-line modularity ceiling — a new re-export would push it
# over and force an unrelated split. ``Base.metadata`` is unaffected either way (``models`` already
# imports ``models_auth``, so every table in it registers).
from mosaera_memory.models_auth import LoginBackoff, OAuthState
from mosaera_memory.store._base import StoreBase, _api_key_summary, _user_summary

_SETUP_TOKEN_ID = 1  # the single setup-token row's fixed primary key

# Backoff clamps. Both are needed and neither is cosmetic:
#   LOGIN_BACKOFF_EXP_CAP bounds the EXPONENT. SQL's LEAST does not short-circuit — it evaluates
#   both arms — so an unclamped power(2, attempts - threshold) overflows `double precision` once an
#   attacker has kept counting, turning every subsequent POST /auth/login into a 500. Capping at
#   2^32 saturates any sane max_seconds long before that. It is exported (and imported by the API's
#   mirror schedule) so the clamp lives in exactly one place.
#   _ATTEMPTS_CAP bounds the stored COUNTER so it can't climb forever past the point where it
#   stops meaning anything (the schedule is already saturated by the exponent cap).
LOGIN_BACKOFF_EXP_CAP = 32
_ATTEMPTS_CAP = 10_000


class AuthMixin(StoreBase):
    # --- users + sessions (multi-user login) ---

    def count_users(self) -> int:
        with self.session() as s:
            return int(s.scalar(select(func.count()).select_from(User)) or 0)

    #: Advisory-lock key for claiming an empty instance. Any constant does; this one is arbitrary
    #: and unique to the purpose.
    _CLAIM_LOCK = 0x4D_4F_53_41

    def create_user(
        self,
        username: str,
        password_hash: str,
        is_admin: bool = False,
        max_users: int = 5,
        require_first: bool = False,
    ) -> dict[str, Any]:
        """Create an account, enforcing the seat cap and unique username (both checked
        inside one transaction). Raises ValueError('user_limit'|'username_taken').

        `require_first` claims an EMPTY instance: it fails with 'already_claimed' if any account
        exists. Checked under a transaction-scoped advisory lock, because the caller's own
        check-then-create is not atomic — two `mosaera-setup` runs racing each other both passed
        "is it empty?" and both created an administrator on a first-run instance.
        """
        username = username.strip()
        with self.session() as s, s.begin():
            if require_first:
                # Serialises the claim. READ COMMITTED alone lets both transactions see zero users.
                with suppress(Exception):  # non-Postgres stores fall back to the check below
                    s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": self._CLAIM_LOCK})
                if int(s.scalar(select(func.count()).select_from(User)) or 0) > 0:
                    raise ValueError("already_claimed")
            if int(s.scalar(select(func.count()).select_from(User)) or 0) >= max_users:
                raise ValueError("user_limit")
            if s.scalar(select(User).where(User.username == username)) is not None:
                raise ValueError("username_taken")
            user = User(username=username, password_hash=password_hash, is_admin=is_admin)
            s.add(user)
            s.flush()
            return _user_summary(user)

    def get_user_credentials(self, username: str) -> dict[str, Any] | None:
        """Auth-only projection INCLUDING the password hash — for login verification."""
        with self.session() as s:
            u = s.scalar(select(User).where(User.username == username.strip()))
            if u is None:
                return None
            return {
                "id": u.id,
                "username": u.username,
                "password_hash": u.password_hash,
                "is_admin": u.is_admin,
            }

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self.session() as s:
            u = s.get(User, user_id)
            return _user_summary(u) if u is not None else None

    def list_users(self) -> list[dict[str, Any]]:
        stmt = select(User).order_by(User.id)
        with self.session() as s:
            return [_user_summary(u) for u in s.scalars(stmt)]

    def count_admins(self) -> int:
        with self.session() as s:
            return int(s.scalar(select(func.count()).select_from(User).where(User.is_admin)) or 0)

    def delete_user(self, user_id: int) -> bool:
        with self.session() as s, s.begin():
            u = s.get(User, user_id)
            if u is None:
                return False
            s.delete(u)  # cascades to the user's sessions
            return True

    def set_user_password(
        self, user_id: int, password_hash: str, *, subject_hash: str | None = None
    ) -> None:
        """Rotate a user's password, revoke their existing sessions, and (given ``subject_hash``)
        clear their login-backoff bucket.

        The bucket clear matters: an admin resetting a locked-out member's password would otherwise
        hand them a working password they still can't use until the backoff expires. The caller
        supplies the hash rather than this layer deriving it — the subject vocabulary belongs to the
        API (``login_subject``), and ``memory`` stays a leaf that counts (see ``LoginBackoff``).
        """
        with self.session() as s, s.begin():
            u = s.get(User, user_id)
            if u is None:
                return
            u.password_hash = password_hash
            for sess in list(u.sessions):
                s.delete(sess)
            if subject_hash is not None:
                s.execute(delete(LoginBackoff).where(LoginBackoff.subject_hash == subject_hash))

    def create_session(self, token_hash: str, user_id: int, expires_at: datetime) -> None:
        with self.session() as s, s.begin():
            s.add(UserSession(token_hash=token_hash, user_id=user_id, expires_at=expires_at))

    def session_user(self, token_hash: str, now: datetime) -> dict[str, Any] | None:
        """The account behind a live (unexpired) session token hash, or None."""
        stmt = select(UserSession).where(
            UserSession.token_hash == token_hash, UserSession.expires_at > now
        )
        with self.session() as s:
            sess = s.scalar(stmt)
            if sess is None or sess.user is None:
                return None
            return _user_summary(sess.user)

    def delete_session(self, token_hash: str) -> None:
        with self.session() as s, s.begin():
            sess = s.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
            if sess is not None:
                s.delete(sess)

    def prune_sessions(self, now: datetime) -> int:
        """Sweep expired sessions; returns how many were removed.

        Set-based on purpose. This runs on EVERY login — an unauthenticated, middleware-exempt
        endpoint — so the previous shape (SELECT every expired row, then ORM-delete them one at a
        time) let any anonymous client trigger an N+1 delete sweep at will. ``user_sessions`` has
        no children (the cascade runs FROM ``users``), so a single DELETE loses nothing.
        """
        with self.session() as s, s.begin():
            result = s.execute(delete(UserSession).where(UserSession.expires_at <= now))
            return int(cast("CursorResult[Any]", result).rowcount)

    # --- login backoff (#38, ADR-0051) ---

    def claim_login_attempt(
        self,
        subject_hash: str,
        *,
        threshold: int,
        base_seconds: int,
        max_seconds: int,
        reset_seconds: int,
        now: datetime | None = None,
        attempts_cap: int = _ATTEMPTS_CAP,
        exp_cap: int = LOGIN_BACKOFF_EXP_CAP,
    ) -> int | None:
        """Spend one login attempt for ``subject_hash`` iff it is not currently backed off.

        Returns the new attempt count when a slot was claimed, or **None** when the subject is
        backed off (claiming nothing — a refused attempt must not extend its own lock, or an
        attacker hammering a bucket would keep it shut forever, and the counter would stop meaning
        "attempts spent").

        **Why the claim happens BEFORE the password check, and why this is one statement.**
        Verification costs ~130ms of scrypt. The obvious design — read the counter, compare, run
        scrypt, increment on failure — leaves a 130ms-wide window in which *every* concurrent
        request reads the same under-threshold count, passes the gate, and gets a guess. The
        threshold would then bound sequential ROUNDS, not guesses: a caller with N connections buys
        N guesses per window instead of ``threshold``. That is the read-then-write race ADR-0050 §5
        rejects for the run quota, and the control's headline number would be fiction. So the
        counter tracks *admitted attempts*, the slot is claimed up front, and success clears the
        bucket (``clear_login_failures``) — which is what preserves "consecutive failures" as the
        effective semantics.

        The whole policy rides in as **bound parameters**, so nothing derived is stored: no
        ``locked_until`` column to go stale when config changes, and the schedule is expressible in
        the ``WHERE`` — which is precisely what makes the check and the claim one atomic step.
        """
        if threshold <= 0:  # defensive: a disabled backoff must never reach the DB
            raise ValueError("claim_login_attempt requires a positive threshold")
        stamp = now or datetime.now(UTC)
        tbl = LoginBackoff.__table__
        moment = sa.literal(stamp, type_=sa.DateTime(timezone=True))
        # Seconds since the last attempt, as float8. Epoch arithmetic rather than interval juggling.
        elapsed = func.extract("epoch", moment - tbl.c.last_attempt_at)
        # The escalating schedule, in SQL so it can gate the UPSERT. Mirrored (for Retry-After only)
        # by mosaera_api.loginbackoff.backoff_seconds; a parametrized test pins the two together.
        lock_seconds = func.least(
            sa.cast(max_seconds, sa.Float),
            sa.cast(base_seconds, sa.Float)
            * func.power(2, func.least(exp_cap, tbl.c.attempts - threshold)),
        )
        stmt = (
            pg_insert(LoginBackoff)
            .values(
                subject_hash=subject_hash,
                attempts=1,
                last_attempt_at=stamp,
                created_at=stamp,
                updated_at=stamp,
            )
            .on_conflict_do_update(
                constraint="uq_login_backoff_subject",
                set_={
                    # Idle long enough → this is a fresh streak, not a continuation.
                    "attempts": sa.case(
                        (elapsed >= reset_seconds, sa.literal(1)),
                        else_=func.least(tbl.c.attempts + 1, attempts_cap),
                    ),
                    "last_attempt_at": stamp,
                    "updated_at": stamp,
                },
                # The atomic gate. The first arm is required: without it, attempts BELOW the
                # threshold would still have to wait out base_seconds (power(2, negative) is a
                # fraction, but LEAST would still impose a delay), throttling honest typos.
                where=sa.or_(tbl.c.attempts < threshold, elapsed >= lock_seconds),
            )
            .returning(tbl.c.attempts)
        )
        with self.session() as s, s.begin():
            return s.execute(stmt).scalar_one_or_none()

    def get_login_backoff(self, subject_hash: str) -> dict[str, Any] | None:
        """A subject's bucket, or None when it has none.

        Read-only, and used ONLY to render ``Retry-After`` on a refused attempt. Never use it to
        decide admission: that check must be the atomic claim above, or the race it exists to close
        comes straight back (the same warning ``run_quota_used`` carries).
        """
        stmt = select(LoginBackoff).where(LoginBackoff.subject_hash == subject_hash)
        with self.session() as s:
            row = s.scalar(stmt)
            if row is None:
                return None
            return {"attempts": row.attempts, "last_attempt_at": row.last_attempt_at}

    def clear_login_failures(self, subject_hash: str) -> None:
        """Drop a subject's bucket — on a successful login, or an admin unlock."""
        with self.session() as s, s.begin():
            s.execute(delete(LoginBackoff).where(LoginBackoff.subject_hash == subject_hash))

    def prune_login_backoff(self, older_than: datetime, *, limit: int = 1000) -> int:
        """Sweep buckets untouched since ``older_than``; returns how many went.

        Bounded (``limit``) and set-based because these rows are attacker-controlled in a way the
        run-quota rows are not: every distinct *submitted* username makes one, so a spray of random
        usernames grows the table without limit. The caller sweeps opportunistically rather than on
        every request — see ADR-0051.
        """
        doomed = (
            select(LoginBackoff.id).where(LoginBackoff.last_attempt_at < older_than).limit(limit)
        )
        with self.session() as s, s.begin():
            result = s.execute(delete(LoginBackoff).where(LoginBackoff.id.in_(doomed)))
            return int(cast("CursorResult[Any]", result).rowcount)

    # --- OAuth "Connect" state (ADR-0104) ---

    def mint_oauth_state(
        self, state_hash: str, user_id: int, project_id: str, provider: str, expires_at: datetime
    ) -> None:
        """Store one in-flight OAuth handshake: the SHA-256 of a random state, bound to the
        initiating admin + selected project + provider, with a short TTL. Plaintext is never
        passed here (the caller hashes). Called by the admin-gated start endpoint."""
        with self.session() as s, s.begin():
            s.add(
                OAuthState(
                    state_hash=state_hash,
                    user_id=user_id,
                    project_id=project_id,
                    provider=provider,
                    expires_at=expires_at,
                )
            )

    def spend_oauth_state(
        self, state_hash: str, provider: str, now: datetime
    ) -> dict[str, Any] | None:
        """Atomically DELETE the matching state row and return its binding, or None if there is no
        live match. SINGLE-USE and race-safe: DELETE ... RETURNING row-locks so exactly one caller
        wins — a replayed callback finds nothing. The row is spent (deleted) even when EXPIRED, so
        a stale state can't be retried; expiry is enforced here by returning None past its TTL.
        ``provider`` is matched too — a state minted for one provider can't be spent by another."""
        stmt = (
            delete(OAuthState)
            .where(OAuthState.state_hash == state_hash, OAuthState.provider == provider)
            .returning(
                OAuthState.user_id,
                OAuthState.project_id,
                OAuthState.provider,
                OAuthState.expires_at,
            )
        )
        with self.session() as s, s.begin():
            row = s.execute(stmt).first()
            if row is None:
                return None
            if row.expires_at < now:  # spent-but-expired → treated as no match (already deleted)
                return None
            return {
                "user_id": row.user_id,
                "project_id": row.project_id,
                "provider": row.provider,
            }

    def sweep_expired_oauth_states(self, older_than: datetime, limit: int = 500) -> int:
        """Opportunistically delete states past their TTL (abandoned handshakes never spent).
        Bounded per call; mirrors the login-backoff sweep. Best-effort housekeeping."""
        doomed = select(OAuthState.id).where(OAuthState.expires_at < older_than).limit(limit)
        with self.session() as s, s.begin():
            result = s.execute(delete(OAuthState).where(OAuthState.id.in_(doomed)))
            return int(cast("CursorResult[Any]", result).rowcount)

    # --- API keys (ADR-0127) ---------------------------------------------------------------

    def create_api_key(self, token_hash: str, user_id: int, name: str) -> dict[str, Any]:
        """Record an issued key. The caller keeps the plaintext; only its hash lands here."""
        with self.session() as s, s.begin():
            key = ApiKey(token_hash=token_hash, user_id=user_id, name=name[:64])
            s.add(key)
            s.flush()
            return _api_key_summary(key)

    def api_key_owner(self, token_hash: str) -> dict[str, Any] | None:
        """The account behind a LIVE key hash, or None when unknown or revoked.

        Looked up BY the hash -- one indexed query, never a scan comparing every stored key. The
        hash is the index, so an unknown key costs the same as a known one.

        **This projection deliberately omits `is_admin`.** `_user_summary` carries it, and
        returning that shape here would hand an admin's key admin authority the moment any caller
        read the flag -- ADR-0004's "the token is not admin" broken by a convenient reuse. The
        distinct shape makes a key holder structurally unable to be mistaken for a session user.
        """
        stmt = select(ApiKey).where(ApiKey.token_hash == token_hash, ApiKey.revoked_at.is_(None))
        with self.session() as s:
            key = s.scalar(stmt)
            if key is None or key.user is None:
                return None
            return {"user_id": key.user.id, "username": key.user.username, "key_id": key.id}

    def touch_api_key(self, token_hash: str, now: datetime, stale_after_s: int = 300) -> None:
        """Record use, but only when the stored stamp is already stale.

        Authentication happens on every request; a write on every request would make a key
        materially more expensive than a session for no operational gain. Coarse to the nearest
        few minutes answers the only question an operator asks of it -- is this key still in use,
        or safe to revoke?
        """
        with self.session() as s, s.begin():
            key = s.scalar(select(ApiKey).where(ApiKey.token_hash == token_hash))
            if key is None:
                return
            last = key.last_used_at
            if last is not None:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                if (now - last).total_seconds() < stale_after_s:
                    return
            key.last_used_at = now

    def list_api_keys(self, user_id: int) -> list[dict[str, Any]]:
        """A user's keys, newest first, WITHOUT the secret -- there is no way back to it."""
        stmt = select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.id.desc())
        with self.session() as s:
            return [_api_key_summary(k) for k in s.scalars(stmt)]

    def revoke_api_key(self, key_id: int, user_id: int, now: datetime) -> bool:
        """Revoke one of ``user_id``'s own keys. True if it was live and is now revoked.

        Scoped to the owner in the QUERY, not checked afterwards: a route that forgot the check
        could otherwise revoke another user's credential. Idempotent -- revoking twice is False
        the second time, not an error.
        """
        stmt = select(ApiKey).where(
            ApiKey.id == key_id, ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None)
        )
        with self.session() as s, s.begin():
            key = s.scalar(stmt)
            if key is None:
                return False
            key.revoked_at = now
            return True
