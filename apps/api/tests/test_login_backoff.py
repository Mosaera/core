"""Per-account login backoff + the enumeration equalization (#38, ADR-0051).

The units (config, schedule, normalization, the dummy hash) run anywhere. The flow tests need a
real database, because the backoff is durable by design — they self-skip like the rest of the
DB-gated suite.

The two most important tests here are regressions against defects that were live before this
change: `test_an_unknown_username_costs_the_same_as_a_real_one` (the ~130ms timing oracle) and
`test_the_429_arrives_at_the_same_point_for_real_and_fictional_accounts` (the status oracle the
backoff would have introduced). Both fail against the previous implementation.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mosaera_api.auth import _DUMMY_HASH, hash_password, login_subject, normalize_username
from mosaera_api.loginguard import (
    LoginBackoffConfig,
    backoff_seconds,
    load_backoff_config,
    verify_slot,
)

_PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MOSAERA_LOGIN_BACKOFF_THRESHOLD",
        "MOSAERA_LOGIN_BACKOFF_BASE_SECONDS",
        "MOSAERA_LOGIN_BACKOFF_MAX_SECONDS",
        "MOSAERA_LOGIN_BACKOFF_RESET_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


# --- units: config ---


def test_defaults_are_on() -> None:
    """Unlike the run quota (a fairness policy → default off), this is a security control, so
    deny-by-default applies and it ships on."""
    config = load_backoff_config()
    assert config == LoginBackoffConfig(
        threshold=5, base_seconds=30, max_seconds=900, reset_seconds=3600
    )
    assert config.enabled is True


def test_threshold_zero_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_LOGIN_BACKOFF_THRESHOLD", "0")
    assert load_backoff_config().enabled is False


@pytest.mark.parametrize("bad", ["5s", "abc", "1.5", "-1", "100001"])
def test_nonsense_config_exits_loudly(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("MOSAERA_LOGIN_BACKOFF_THRESHOLD", bad)
    with pytest.raises(SystemExit):
        load_backoff_config()


def test_a_reset_window_shorter_than_the_max_lock_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cross-field invariant no per-value range check can catch, whose failure is SILENT:
    with reset <= max, the idle-reset always fires before a lock can escalate, so the ladder is
    pinned at its first tier forever and nothing says so."""
    monkeypatch.setenv("MOSAERA_LOGIN_BACKOFF_MAX_SECONDS", "900")
    monkeypatch.setenv("MOSAERA_LOGIN_BACKOFF_RESET_SECONDS", "600")
    with pytest.raises(SystemExit, match="GREATER"):
        load_backoff_config()


def test_a_disabled_backoff_skips_the_cross_field_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_LOGIN_BACKOFF_THRESHOLD", "0")
    monkeypatch.setenv("MOSAERA_LOGIN_BACKOFF_RESET_SECONDS", "1")
    assert load_backoff_config().enabled is False  # no SystemExit — nothing to be incoherent about


# --- units: the schedule ---


def test_the_schedule_escalates_and_caps() -> None:
    config = load_backoff_config()
    assert [backoff_seconds(a, config) for a in range(0, 12)] == [
        0,
        0,
        0,
        0,
        0,  # below the threshold: no wait at all
        30,
        60,
        120,
        240,
        480,
        900,
        900,  # doubling, then pinned at max_seconds
    ]


def test_the_schedule_is_flat_when_disabled() -> None:
    config = LoginBackoffConfig(threshold=0, base_seconds=30, max_seconds=900, reset_seconds=3600)
    assert backoff_seconds(99, config) == 0


# --- units: normalization (the bypass surface) ---


@pytest.mark.parametrize("variant", ["admin", " admin", "admin ", "\tadmin\n", "  admin  "])
def test_whitespace_variants_share_one_bucket(variant: str) -> None:
    """`get_user_credentials` strips, so these all resolve to ONE account. If the bucket key didn't
    strip identically, each variant would buy a fresh allowance — an unlimited-guess bypass."""
    assert login_subject(normalize_username(variant)) == login_subject(normalize_username("admin"))


def test_case_variants_do_not_share_a_bucket() -> None:
    """`users.username` is case-sensitively unique, so `admin` and `Admin` are two accounts that
    can coexist. Folding them into one bucket would be a bypass, not a nicety: a success DELETES
    the bucket, so a member holding `Admin` could clear the real admin's counter at will."""
    assert login_subject(normalize_username("Admin")) != login_subject(normalize_username("admin"))


def test_an_enormous_username_is_capped() -> None:
    assert len(normalize_username("a" * 100_000)) == 256  # the body schema bounds nothing


def test_the_bucket_key_never_holds_the_username() -> None:
    assert "admin" not in login_subject(normalize_username("admin"))


# --- units: the dummy hash ---


def test_the_dummy_hash_matches_a_real_one_and_never_verifies() -> None:
    """The equalizer. It must be indistinguishable in cost from a real stored hash — which means
    identical scrypt params — and must never accept any password."""
    real = hash_password("whatever")
    assert _DUMMY_HASH.split("$")[:4] == real.split("$")[:4]  # scheme + n + r + p
    assert len(_DUMMY_HASH.split("$")[5]) == len(real.split("$")[5])  # same dklen ⇒ same work
    from mosaera_api.auth import verify_password

    assert verify_password("", _DUMMY_HASH) is False
    assert verify_password("admin", _DUMMY_HASH) is False


# --- units: the verification bound ---


def test_verify_slots_are_bounded_and_released() -> None:
    """Non-blocking by contract: exhausting the slots must refuse, never queue — queueing would
    hold an anyio worker, which is the DoS it exists to prevent."""
    from mosaera_api import loginguard

    held = [loginguard._verify_gate.acquire(blocking=False) for _ in range(64)]
    try:
        with verify_slot() as slot:
            assert slot is False  # refused rather than blocked
    finally:
        for got in held:
            if got:
                loginguard._verify_gate.release()
    with verify_slot() as slot:
        assert slot is True  # released back on exit


# --- DB-gated flow ---


def _reachable(url: str | None) -> bool:
    if not url:
        return False
    try:
        from mosaera_memory import MemoryStore

        MemoryStore.from_url(url).init()
        return True
    except Exception:
        return False


# Read at import: the repo-root autouse fixture strips MOSAERA_* per test.
_DB_URL = os.environ.get("MOSAERA_TEST_DB_URL")

# The gate lives in the repo-root conftest (#58): probed once, reason printed,
# and an ERROR rather than a skip when MOSAERA_INTEGRATION=required.
requires_db = pytest.mark.requires_db


def _fake_factory(req: Any, run_id: str) -> Any:
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class S(TypedDict, total=False):
        task: str

    b: StateGraph = StateGraph(S)
    b.add_node("n", lambda s: {"task": s.get("task", "")})
    b.add_edge(START, "n")
    b.add_edge("n", END)
    return b.compile(), {"configurable": {"thread_id": run_id}}, {"task": req.task}, None


def _wipe(s: Any) -> None:
    """A genuinely fresh instance. The backoff buckets matter as much as the users here: these
    tests share a dev database and reuse `admin1`, so a streak left by one test would throttle the
    next one's setup login (it did — 429 before a single deliberate failure)."""
    from mosaera_memory.models_auth import LoginBackoff
    from sqlalchemy import delete

    for u in s.list_users():
        s.delete_user(u["id"])
    with s.session() as sess, sess.begin():
        sess.execute(delete(LoginBackoff))


@pytest.fixture
def store() -> Iterator[Any]:
    from mosaera_memory import MemoryStore

    s = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    s.init()
    _wipe(s)
    yield s
    _wipe(s)


def _client(monkeypatch: pytest.MonkeyPatch, store: Any, **env: str) -> TestClient:
    """A client with the backoff config pinned. Config resolves at app BUILD (so a bad value can't
    reach a request), hence env must be set before create_app."""
    from mosaera_api.app import create_app

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return TestClient(create_app(graph_factory=_fake_factory, memory=store))


def _make_admin(store: Any, username: str = "admin1") -> None:
    """The first administrator, created the way the product creates one (ADR-0116).

    This whole suite used to bootstrap through `POST /auth/setup` with a one-time token. That
    endpoint is gone — there is no browser route that creates an account — so the fixture does what
    `mosaera-setup` does: writes the account to the store directly. Nothing about the backoff
    behaviour under test depends on how the account got there.
    """
    from mosaera_api.auth import hash_password

    store.create_user(username, hash_password(_PASSWORD), is_admin=True)


_WRONG = "wrong-password"


def _login(client: TestClient, username: str, password: str = _WRONG) -> Any:
    return client.post("/api/auth/login", json={"username": username, "password": password})


@requires_db
def test_failures_back_off_then_recover(monkeypatch: pytest.MonkeyPatch, store: Any) -> None:
    c = _client(monkeypatch, store, MOSAERA_LOGIN_BACKOFF_THRESHOLD="3")
    _make_admin(store)
    assert [_login(c, "admin1").status_code for _ in range(3)] == [401, 401, 401]
    blocked = _login(c, "admin1")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1  # never 0 — that invites a hot retry loop
    assert "too many" in blocked.json()["detail"]


@requires_db
def test_the_correct_password_is_refused_while_locked(
    monkeypatch: pytest.MonkeyPatch, store: Any
) -> None:
    """The lockout is real, and this is the accepted cost: throttling guessing means an attacker
    who knows a username can hold that account out. Documented in ADR-0051 + TM-0002; the operator
    escape hatch is the service/admin token, which bypasses /auth/login entirely."""
    c = _client(monkeypatch, store, MOSAERA_LOGIN_BACKOFF_THRESHOLD="2")
    _make_admin(store)
    for _ in range(2):
        _login(c, "admin1")
    assert _login(c, "admin1", _PASSWORD).status_code == 429  # right password, still refused


@requires_db
def test_a_success_ends_the_streak(monkeypatch: pytest.MonkeyPatch, store: Any) -> None:
    c = _client(monkeypatch, store, MOSAERA_LOGIN_BACKOFF_THRESHOLD="3")
    _make_admin(store)
    _login(c, "admin1")
    _login(c, "admin1")
    assert _login(c, "admin1", _PASSWORD).status_code == 200  # succeeds, clearing the bucket
    assert store.get_login_backoff(login_subject("admin1")) is None
    assert [_login(c, "admin1").status_code for _ in range(3)] == [401, 401, 401]  # full allowance


@requires_db
def test_the_429_arrives_at_the_same_point_for_real_and_fictional_accounts(
    monkeypatch: pytest.MonkeyPatch, store: Any
) -> None:
    """The status-oracle regression.

    Backoff necessarily branches on account state. If only real accounts backed off, the 429 would
    itself announce "this username exists" — a cleaner oracle than the timing leak this change
    closes. Both must throttle identically.
    """
    c = _client(monkeypatch, store, MOSAERA_LOGIN_BACKOFF_THRESHOLD="3")
    _make_admin(store)
    real = [_login(c, "admin1").status_code for _ in range(4)]
    fictional = [_login(c, "no-such-user").status_code for _ in range(4)]
    assert real == fictional == [401, 401, 401, 429]


@requires_db
def test_an_unknown_username_costs_the_same_as_a_real_one(
    monkeypatch: pytest.MonkeyPatch, store: Any
) -> None:
    """The timing-oracle regression — the defect this change exists to close.

    `ok = creds is not None and verify_password(...)` short-circuits, so an unknown username used
    to skip ~130ms of scrypt entirely: a ~100x gap readable in a SINGLE request, while
    TM-0002 claimed the work was "constant-ish whether or not the user exists".

    The bound is deliberately loose (half) — this is wall-clock in CI, and the defect it guards
    against is two orders of magnitude, not a few percent. Backoff is off so every attempt verifies.
    """
    c = _client(monkeypatch, store, MOSAERA_LOGIN_BACKOFF_THRESHOLD="0")
    _make_admin(store)

    def elapsed(username: str) -> float:
        start = time.perf_counter()
        assert _login(c, username).status_code == 401
        return time.perf_counter() - start

    _login(c, "warmup")  # first-call noise (imports, pool)
    known = min(elapsed("admin1") for _ in range(3))
    unknown = min(elapsed(f"ghost-{uuid.uuid4().hex[:8]}") for _ in range(3))
    assert unknown > known * 0.5, f"unknown={unknown:.3f}s known={known:.3f}s — the oracle is back"


@requires_db
def test_whitespace_variants_cannot_buy_extra_attempts(
    monkeypatch: pytest.MonkeyPatch, store: Any
) -> None:
    c = _client(monkeypatch, store, MOSAERA_LOGIN_BACKOFF_THRESHOLD="3")
    _make_admin(store)
    for variant in ("admin1", " admin1", "admin1 "):
        assert _login(c, variant).status_code == 401
    assert _login(c, "\tadmin1  ").status_code == 429  # same bucket, allowance already spent


@requires_db
def test_a_case_sibling_cannot_clear_another_accounts_streak(
    monkeypatch: pytest.MonkeyPatch, store: Any
) -> None:
    """The casefold regression. `admin1` and `Admin1` are distinct accounts; if they shared a
    bucket, `Admin1` logging in successfully would wipe `admin1`'s counter — a member resetting the
    admin's throttle at will."""
    c = _client(monkeypatch, store, MOSAERA_LOGIN_BACKOFF_THRESHOLD="3")
    _make_admin(store, "admin1")
    admin_session = c.post("/api/auth/login", json={"username": "admin1", "password": _PASSWORD})
    assert admin_session.status_code == 200
    resp = c.post(
        "/api/auth/users",
        json={"username": "Admin1", "password": _PASSWORD, "is_admin": False},
    )
    assert resp.status_code == 201, resp.text

    c.cookies.clear()
    for _ in range(3):
        _login(c, "admin1")  # burn admin1's allowance
    assert _login(c, "Admin1", _PASSWORD).status_code == 200  # the sibling logs in fine…
    assert _login(c, "admin1", _PASSWORD).status_code == 429  # …and admin1 is still throttled


@requires_db
def test_an_admin_can_clear_a_lockout(monkeypatch: pytest.MonkeyPatch, store: Any) -> None:
    c = _client(monkeypatch, store, MOSAERA_LOGIN_BACKOFF_THRESHOLD="2")
    _make_admin(store, "admin1")
    c.post("/api/auth/login", json={"username": "admin1", "password": _PASSWORD})
    member = c.post(
        "/api/auth/users", json={"username": "member1", "password": _PASSWORD, "is_admin": False}
    )
    assert member.status_code == 201
    member_id = member.json()["user"]["id"]

    for _ in range(2):
        _login(c, "member1")
    assert _login(c, "member1", _PASSWORD).status_code == 429

    assert c.delete(f"/api/auth/users/{member_id}/lockout").status_code == 200
    assert _login(c, "member1", _PASSWORD).status_code == 200  # unlocked


@requires_db
def test_clearing_a_lockout_requires_admin(monkeypatch: pytest.MonkeyPatch, store: Any) -> None:
    c = _client(monkeypatch, store, MOSAERA_LOGIN_BACKOFF_THRESHOLD="5")
    _make_admin(store, "admin1")
    c.post("/api/auth/login", json={"username": "admin1", "password": _PASSWORD})
    member = c.post(
        "/api/auth/users", json={"username": "member1", "password": _PASSWORD, "is_admin": False}
    )
    member_id = member.json()["user"]["id"]
    c.cookies.clear()
    c.post("/api/auth/login", json={"username": "member1", "password": _PASSWORD})
    assert c.delete(f"/api/auth/users/{member_id}/lockout").status_code == 403  # not an admin


@requires_db
def test_a_disabled_backoff_never_throttles(monkeypatch: pytest.MonkeyPatch, store: Any) -> None:
    c = _client(monkeypatch, store, MOSAERA_LOGIN_BACKOFF_THRESHOLD="0")
    _make_admin(store)
    assert {_login(c, "admin1").status_code for _ in range(12)} == {401}
    assert store.get_login_backoff(login_subject("admin1")) is None  # no rows written at all


@requires_db
def test_the_sql_schedule_agrees_with_the_python_mirror(
    monkeypatch: pytest.MonkeyPatch, store: Any
) -> None:
    """The drift guard.

    The schedule has to live in SQL (the predicate must be in the WHERE for check-and-claim to be
    atomic), and `backoff_seconds` mirrors it only to render Retry-After. This asserts the SQL's
    admission decision matches the Python wait at every rung: one second before the mirror says the
    wait is over the claim is refused; exactly at it, the claim is admitted.
    """
    from datetime import UTC, datetime, timedelta

    config = load_backoff_config()
    policy = {
        "threshold": config.threshold,
        "base_seconds": config.base_seconds,
        "max_seconds": config.max_seconds,
        "reset_seconds": config.reset_seconds,
    }
    subject = uuid.uuid4().hex
    at = datetime(2026, 7, 17, 12, 0, 0, tzinfo=UTC)
    for _ in range(config.threshold):
        store.claim_login_attempt(subject, **policy, now=at)

    for attempts in range(config.threshold, config.threshold + 4):
        wait = backoff_seconds(attempts, config)
        assert (
            store.claim_login_attempt(subject, **policy, now=at + timedelta(seconds=wait - 1))
            is None
        )
        at = at + timedelta(seconds=wait)
        assert store.claim_login_attempt(subject, **policy, now=at) == attempts + 1
