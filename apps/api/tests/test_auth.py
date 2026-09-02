"""Multi-user auth: password hashing (unit) + the login/session/role flow (DB-gated).

The flow tests skip unless MOSAERA_TEST_DB_URL points at a reachable database (user
accounts require durable storage). The hashing/validation units always run.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mosaera_api.auth import (
    hash_password,
    users_exist,
    validate_credentials,
    verify_password,
)

# --- units (no DB) ---


def test_password_hash_roundtrip_and_rejects_wrong() -> None:
    h = hash_password("correct horse battery")
    assert h.startswith("scrypt$")
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong", h)
    # A malformed/garbage stored hash never verifies (and never raises).
    assert not verify_password("x", "not-a-real-hash")
    # Two hashes of the same password differ (random salt).
    assert hash_password("same") != hash_password("same")


def test_validate_credentials() -> None:
    assert validate_credentials("ab", "longenough1") is not None  # username too short
    assert validate_credentials("alex", "short") is not None  # password too short
    assert validate_credentials("bad name", "longenough1") is not None  # space not allowed
    assert validate_credentials("alex.r-1", "longenough1") is None  # ok


def test_users_exist_tolerates_missing_store() -> None:
    # No store at all → no accounts. Only reachable when no DB is configured, or under the
    # explicit MOSAERA_ALLOW_DEGRADED_MEMORY opt-in — guard_memory refuses to boot otherwise.
    assert users_exist(None) is False


def test_users_exist_ignores_a_store_with_no_account_support() -> None:
    # A store with no `count_users` has no account tier at all (a duck-typed fake, or a build
    # without the users table). That is a CAPABILITY answer, not a failure — it must not be
    # mistaken for a broken store and trip the fail-closed path below.
    class _NoAccounts:
        pass

    assert users_exist(_NoAccounts()) is False  # type: ignore[arg-type]


def test_users_exist_fails_closed_when_a_live_store_errors() -> None:
    # The opposite direction, deliberately (ADR-0035): a store that DOES support accounts but
    # throws when asked must not silently switch authentication OFF. The accounts guarding
    # this API do not cease to exist because we momentarily cannot read them — callers get a
    # 401, not an open API. The discriminator is the store's capability, not the exception:
    # collapsing these two cases is exactly how the fail-open bug happened.
    class _DeadStore:
        def count_users(self) -> int:
            raise RuntimeError("connection reset")

    assert users_exist(_DeadStore()) is True  # type: ignore[arg-type]


# --- there is no browser route that creates an account (ADR-0116) ------------------------------


def _client_for(store: Any) -> TestClient:
    from mosaera_api.app import create_app

    return TestClient(create_app(graph_factory=_fake_factory, memory=store))


class _EmptyStore:
    """A store with the account tier and nothing in it — the state the race needed."""

    def count_users(self) -> int:
        return 0


def test_no_endpoint_mints_the_first_admin() -> None:
    """The CWE-1188 fix, and it is now structural rather than guarded.

    `POST /auth/setup` was middleware-exempt and created the first administrator, so on any
    reachable-but-uninitialised instance a client could race the operator for it. ADR-0040 closed
    that with a one-time token printed to the logs. ADR-0116 closes it by construction: setup
    happens in a terminal, the endpoint is gone, and a 404 cannot be raced.
    """
    c = _client_for(_EmptyStore())
    for path in ("/api/auth/setup", "/api/auth/setup/check"):
        # 404 OR 405, and the distinction is not this test's business. The SPA catch-all answers GET
        # on every path, so when it is mounted a route that no longer accepts POST reports the
        # METHOD (405); when it is not, the PATH is simply absent (404). Which one you get depends
        # on whether `apps/web/dist` exists — and `make ci` runs `test` BEFORE `build`, so CI never
        # has it while a developer box that has built once always does. Pinning 405 made the test
        # pass locally and fail in CI for a reason that has nothing to do with the invariant, which
        # is that NOTHING MINTS THE FIRST ADMIN. Both statuses prove exactly that.
        body = {"username": "a", "password": "secret123"}
        assert c.post(path, json=body).status_code in (404, 405)


def test_the_only_open_endpoints_are_the_ones_that_create_nothing() -> None:
    """What the middleware exempts is the whole unauthenticated surface, so it is worth pinning
    by name rather than by reading two lists and hoping they agree."""
    from mosaera_api import app as app_module

    source = Path(app_module.__file__).read_text(encoding="utf-8")
    open_paths = source[source.index("_open_api_paths = frozenset(") :].split(")")[0]
    assert "/api/auth/status" in open_paths and "/api/auth/login" in open_paths
    assert "/api/auth/setup" not in open_paths


def test_an_empty_instance_says_so_without_offering_a_way_in() -> None:
    """`needs_setup` survives the flow it was built for: the SPA cannot act on it any more, but a
    login form on an instance with no accounts is a door with no key, and saying which command
    creates one is better than saying nothing."""
    status = _client_for(_EmptyStore()).get("/api/auth/status").json()
    assert status["needs_setup"] is True
    assert "needs_setup_token" not in status


# --- DB-gated login/session/role flow ---


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
# Read at IMPORT: the repo-root autouse fixture strips MOSAERA_* per test, so a guard that reads
# the live URL inside a test sees nothing and never fires.
_LIVE_DB_URL = os.environ.get("MOSAERA_DB_URL", "").strip()

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


def _fresh_store() -> Any:
    """A zero-user store, which these tests genuinely require: what happens on an instance with no
    accounts can only be tested when there are none.

    That makes the teardown DESTRUCTIVE by design — it deletes every user, not just the ones a
    test made — so it refuses to run against a database that is also serving the app. A live
    admin account was wiped this way on 2026-08-05 by pointing MOSAERA_TEST_DB_URL at the dev
    database; the fix is not a gentler teardown (there isn't one that still tests first-run) but
    a hard stop before the damage.
    """
    from mosaera_memory import MemoryStore

    if _LIVE_DB_URL and _LIVE_DB_URL == str(_DB_URL).strip():
        raise RuntimeError(
            "MOSAERA_TEST_DB_URL points at the SAME database as MOSAERA_DB_URL. These tests "
            "delete every user account to test a fresh instance — point them at a scratch "
            "database instead."
        )
    store = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    store.init()
    for u in store.list_users():
        store.delete_user(u["id"])
    return store


def _setup(
    client: TestClient,
    username: str = "admin1",
    password: str = "secret123",  # noqa: S107 — test-fixture credential, not a real secret
) -> Any:
    """Become the first administrator, the way the product makes one (ADR-0116).

    This used to POST `/auth/setup` with a one-time token. There is no such endpoint any more —
    `mosaera-setup` writes the account to the database directly, from a terminal — so the fixture
    does the same and then logs in, because what these tests are actually about is what an
    authenticated admin may do.
    """
    from mosaera_api.auth import hash_password

    store = client.store  # type: ignore[attr-defined]
    store.create_user(username, hash_password(password), is_admin=True)
    return client.post("/api/auth/login", json={"username": username, "password": password})


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from mosaera_api.app import create_app

    store = _fresh_store()
    c = TestClient(create_app(graph_factory=_fake_factory, memory=store))
    # The store rides along so `_setup` can create the first admin the way the wizard does.
    c.store = store  # type: ignore[attr-defined]
    yield c
    for u in store.list_users():
        store.delete_user(u["id"])


@requires_db
def test_the_first_admin_then_login_logout(client: TestClient) -> None:
    # Open before any account exists — an unconfigured loopback box stays usable (ADR-0004).
    assert client.get("/api/history").status_code == 200
    st = client.get("/api/auth/status").json()
    assert st["needs_setup"] is True and st["auth_required"] is False

    # And no endpoint will make that account for a caller who is not on the machine.
    assert (
        client.post("/api/auth/setup", json={"username": "a", "password": "secret123"}).status_code
        == 404
    )
    assert client.get("/api/auth/status").json()["needs_setup"] is True  # still no admin

    r = _setup(client, "admin1")
    assert r.status_code == 200 and r.json()["user"]["is_admin"] is True
    assert client.get("/api/auth/me").json()["user"]["username"] == "admin1"
    # Auth is now enforced; the cookie carries the session.
    assert client.get("/api/history").status_code == 200
    assert client.get("/api/auth/status").json()["needs_setup"] is False

    client.post("/api/auth/logout")
    assert client.get("/api/history").status_code == 401
    assert (
        client.post("/api/auth/login", json={"username": "admin1", "password": "no"}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"username": "admin1", "password": "secret123"}
        ).status_code
        == 200
    )
    assert client.get("/api/history").status_code == 200


@requires_db
def test_five_seat_cap(client: TestClient) -> None:
    _setup(client, "admin1")
    for i in range(4):  # admin + 4 = 5
        r = client.post("/api/auth/users", json={"username": f"member{i}", "password": "secret123"})
        assert r.status_code == 201
    over = client.post("/api/auth/users", json={"username": "member5", "password": "secret123"})
    assert over.status_code == 409
    assert len(client.get("/api/auth/users").json()["users"]) == 5


@requires_db
def test_member_cannot_manage_users_or_write_config(client: TestClient) -> None:
    _setup(client, "admin1")
    client.post(
        "/api/auth/users", json={"username": "bob", "password": "secret123", "is_admin": False}
    )
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "bob", "password": "secret123"})
    # A member can use the app…
    assert client.get("/api/history").status_code == 200
    # …but not manage accounts or write config (admin only).
    assert client.get("/api/auth/users").status_code == 403
    assert (
        client.post("/api/auth/users", json={"username": "x", "password": "secret123"}).status_code
        == 403
    )
    assert client.put("/api/pricing", json={"prices": {}}).status_code == 403


@requires_db
def test_cannot_remove_last_admin(client: TestClient) -> None:
    setup = _setup(client, "admin1")
    admin_id = setup.json()["user"]["id"]
    assert client.delete(f"/api/auth/users/{admin_id}").status_code == 409  # last admin protected


@requires_db
def test_initial_admin_env_seeds_an_admin_at_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    # The MOSAERA_INITIAL_ADMIN_* escape hatch, and now the ONLY non-terminal way in: an
    # orchestrated deploy never sees a shell, so it pre-provisions its administrator (ADR-0116).
    from mosaera_api.app import create_app

    store = _fresh_store()
    monkeypatch.setenv("MOSAERA_INITIAL_ADMIN_USER", "seededadmin")
    monkeypatch.setenv("MOSAERA_INITIAL_ADMIN_PASSWORD", "secret12345")
    c = TestClient(create_app(graph_factory=_fake_factory, memory=store))
    try:
        assert c.get("/api/auth/status").json()["needs_setup"] is False
        login = c.post(
            "/api/auth/login", json={"username": "seededadmin", "password": "secret12345"}
        )
        assert login.status_code == 200 and login.json()["user"]["is_admin"] is True
    finally:
        for u in store.list_users():
            store.delete_user(u["id"])


@requires_db
def test_first_admin_cannot_be_created_via_auth_users(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Finding A1, and it matters MORE now, not less: even when the admin gate is SATISFIED (here
    # via MOSAERA_ALLOW_REMOTE_CONFIG, standing in for the proxied-loopback case where
    # _require_local_config passes), /auth/users must refuse to mint the FIRST admin. With
    # /auth/setup deleted this is the last endpoint that could conceivably create one, so it is
    # now the whole of the HTTP-side defence.
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    r = client.post(
        "/api/auth/users", json={"username": "sneak", "password": "secret123", "is_admin": True}
    )
    assert r.status_code == 403 and "setup" in r.json()["detail"].lower()
    assert client.get("/api/auth/status").json()["needs_setup"] is True  # still no admin


@requires_db
def test_service_token_grants_api_but_not_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaera_api.app import create_app

    store = _fresh_store()
    store.create_user("admin1", hash_password("secret123"), is_admin=True)  # users exist → enforced
    monkeypatch.setenv("MOSAERA_API_TOKEN", "svc-token")
    c = TestClient(create_app(graph_factory=_fake_factory, memory=store))
    try:
        assert c.get("/api/history").status_code == 401  # no credential
        hdr = {"Authorization": "Bearer svc-token"}
        assert c.get("/api/history", headers=hdr).status_code == 200  # service token → API access
        # …but the plain service token is NOT admin — config writes still refuse.
        assert c.put("/api/pricing", json={"prices": {}}, headers=hdr).status_code == 403
    finally:
        for u in store.list_users():
            store.delete_user(u["id"])
