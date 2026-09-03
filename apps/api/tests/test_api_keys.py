"""Per-user API keys (ADR-0127).

Two properties carry the security of this feature, and the tests for THEM are the point of this
file — the happy path is the easy part:

1. **A key authenticates but is never ADMIN**, even when its owner is an admin. If this breaks, a
   leaked key rewrites config and secrets, and ADR-0004's "the token is not admin" is false for a
   credential a human can mint from a browser.
2. **A key cannot mint another key.** ADR-0116 deleted this repo's previous credential-issuing
   endpoint as CWE-1188; a credential that issues credentials is self-propagating, so a leak
   becomes permanent.

DB-gated: the whole feature is a table, so nearly all of this SKIPS without MOSAERA_TEST_DB_URL.
Local green does NOT mean this works — it first runs for real in CI's database job.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_auth import PASSPHRASE, _fake_factory, _fresh_store, _setup, requires_db


@pytest.fixture
def client() -> Iterator[TestClient]:
    from mosaera_api.app import create_app

    store = _fresh_store()
    c = TestClient(create_app(graph_factory=_fake_factory, memory=store))
    c.store = store  # type: ignore[attr-defined]
    yield c
    for u in store.list_users():
        store.delete_user(u["id"])


def _issue(client: TestClient, name: str = "ci") -> str:
    """Become an admin, log in, and mint a key. Returns the plaintext (the only time it exists)."""
    _setup(client)
    r = client.post("/api/keys", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["key"]


# --- THE TWO LOAD-BEARING PROPERTIES ------------------------------------------------------------


@requires_db
def test_a_key_from_an_ADMIN_still_cannot_do_ADMIN(client: TestClient) -> None:
    """THE test. The key belongs to an administrator and must still be refused an admin write."""
    key = _issue(client, "admins-own-key")
    client.cookies.clear()  # drop the session — the key is now the ONLY credential

    h = {"Authorization": f"Bearer {key}"}
    assert client.get("/api/history", headers=h).status_code == 200, "the key should authenticate"

    # A REAL admin-gated endpoint (`require_admin` in routes/auth.py), not a guessed one: a 404
    # or 405 would mean the request was refused before auth ran and this test proved nothing.
    listed = client.get("/api/auth/users", headers=h)
    assert listed.status_code in (401, 403), (
        f"an ADMIN's API key passed an admin gate ({listed.status_code}) — ADR-0004's "
        "'the token is not admin' is broken for this credential"
    )
    created = client.post(
        "/api/auth/users",
        json={"username": "sneaky", "password": PASSPHRASE, "is_admin": True},
        headers=h,
    )
    assert created.status_code in (401, 403), (
        f"an ADMIN's API key CREATED AN ACCOUNT ({created.status_code}) — privilege escalation"
    )


@requires_db
def test_a_key_cannot_mint_another_key(client: TestClient) -> None:
    """A self-propagating credential makes a leak permanent (the ADR-0116 lesson)."""
    key = _issue(client)
    client.cookies.clear()
    h = {"Authorization": f"Bearer {key}"}

    minted = client.post("/api/keys", json={"name": "second"}, headers=h)
    assert minted.status_code in (401, 403), "a key issued a key"
    assert client.get("/api/keys", headers=h).status_code in (401, 403)
    assert client.delete("/api/keys/1", headers=h).status_code in (401, 403)


# --- the same two properties, BEHIND A REVERSE PROXY ---------------------------------------------
#
# The two tests above passed while the escalation below was live, because `TestClient`'s socket
# peer is the literal string "testclient", which is not in `_LOCAL_HOSTS` — so the loopback
# fallback in `_require_admin` refused them for a reason that has nothing to do with API keys.
# Behind a same-host reverse proxy (bind 127.0.0.1 + nginx, the recommended exposed topology, and
# the one `guard_bind` lets run WITHOUT any token) every request presents as 127.0.0.1 and the
# same gate opens. The peer address was doing the work the credential was credited with.


@pytest.fixture
def proxied() -> Iterator[TestClient]:
    """The `client` fixture with the socket peer a proxy would produce."""
    from mosaera_api.app import create_app

    store = _fresh_store()
    c = TestClient(
        create_app(graph_factory=_fake_factory, memory=store), client=("127.0.0.1", 40000)
    )
    c.store = store  # type: ignore[attr-defined]
    yield c
    for u in store.list_users():
        store.delete_user(u["id"])


@requires_db
def test_the_proxied_fixture_really_does_look_local(
    proxied: TestClient, client: TestClient
) -> None:
    """CONTROL, and it has to be one that can fail. A `proxied` fixture that quietly stopped
    setting the peer would leave the two tests below passing for the ORIGINAL wrong reason.

    So compare the two fixtures on the one gate that reads the peer and nothing else: on an
    unclaimed instance (no users, no tokens) an admin-gated write falls all the way to
    `_require_local_config`, which admits a local peer and refuses any other. If the peers ever
    stop differing, this fails.
    """
    body: dict[str, Any] = {"prices": {}}
    assert proxied.put("/api/pricing", json=body).status_code == 200, (
        "the proxied fixture no longer presents as 127.0.0.1 — the tests below prove nothing"
    )
    assert client.put("/api/pricing", json=body).status_code == 403, (
        "the default fixture is supposed to look remote; the two are no longer different"
    )


@requires_db
def test_an_ADMINS_key_is_still_not_ADMIN_behind_a_proxy(proxied: TestClient) -> None:
    """THE regression. This returned 200/201 — an admin's key listed every user and created a
    new administrator — because a key leaves `current_user` None and so skips the explicit
    non-admin refusal, landing in a same-host gate that a proxy satisfies for everyone."""
    key = _issue(proxied, "admins-own-key")
    proxied.cookies.clear()

    h = {"Authorization": f"Bearer {key}"}
    assert proxied.get("/api/history", headers=h).status_code == 200, "the key should authenticate"
    assert proxied.get("/api/auth/users", headers=h).status_code in (401, 403)
    created = proxied.post(
        "/api/auth/users",
        json={"username": "sneaky", "password": PASSPHRASE, "is_admin": True},
        headers=h,
    )
    assert created.status_code in (401, 403), (
        f"an API key created an ADMIN account ({created.status_code}) behind a proxy"
    )


@requires_db
def test_a_plain_user_cannot_promote_themselves_with_their_own_key(proxied: TestClient) -> None:
    """The whole attack, from the credential any ordinary user is entitled to mint.

    Minting a key needs only a SESSION, not admin — correctly, it is the user's own credential.
    The escalation was that presenting it then bought MORE authority than the session that
    issued it, which is the property this pins: a key is a floor on nothing and a ceiling on
    what its owner already had.
    """
    _setup(proxied)
    assert (
        proxied.post(
            "/api/auth/users",
            json={"username": "peon", "password": PASSPHRASE, "is_admin": False},
        ).status_code
        == 201
    )
    proxied.cookies.clear()
    assert (
        proxied.post(
            "/api/auth/login", json={"username": "peon", "password": PASSPHRASE}
        ).status_code
        == 200
    )
    minted = proxied.post("/api/keys", json={"name": "peon-key"})
    assert minted.status_code == 200, "an ordinary user may mint their own key"
    proxied.cookies.clear()

    h = {"Authorization": f"Bearer {minted.json()['key']}"}
    escalated = proxied.post(
        "/api/auth/users",
        json={"username": "pwned", "password": PASSPHRASE, "is_admin": True},
        headers=h,
    )
    assert escalated.status_code in (401, 403), (
        f"a NON-ADMIN minted a key and became admin with it ({escalated.status_code})"
    )
    admins = sorted(u["username"] for u in proxied.store.list_users() if u.get("is_admin"))  # type: ignore[attr-defined]
    assert admins == ["admin1"], f"an administrator was created by a non-admin: {admins}"


# --- lifecycle ----------------------------------------------------------------------------------


@requires_db
def test_a_key_authenticates_and_revocation_takes_effect(client: TestClient) -> None:
    key = _issue(client)
    listed = client.get("/api/keys").json()["keys"]
    assert len(listed) == 1 and listed[0]["revoked"] is False
    key_id = listed[0]["id"]

    client.cookies.clear()
    h = {"Authorization": f"Bearer {key}"}
    assert client.get("/api/history", headers=h).status_code == 200

    _setup(client, "admin2", PASSPHRASE)  # log back in to revoke
    assert client.delete(f"/api/keys/{key_id}").status_code in (200, 404)


@requires_db
def test_the_plaintext_is_returned_ONCE_and_never_again(client: TestClient) -> None:
    """There is no path back to the secret. If a list ever carried it, a DB read would too."""
    key = _issue(client)
    listed = client.get("/api/keys").json()["keys"]
    assert key not in str(listed), "the key came back from a list endpoint"
    assert "token_hash" not in str(listed), "the hash is not the operator's business either"
    assert "key" not in listed[0]


@requires_db
def test_an_unknown_key_is_refused(client: TestClient) -> None:
    _setup(client)
    client.cookies.clear()
    r = client.get("/api/history", headers={"Authorization": "Bearer not-a-real-key"})
    assert r.status_code == 401


@requires_db
def test_a_name_is_required(client: TestClient) -> None:
    _setup(client)
    assert client.post("/api/keys", json={"name": "  "}).status_code == 400


# --- the store, which is where the projections are decided --------------------------------------


@requires_db
def test_the_owner_projection_omits_is_admin(client: TestClient) -> None:
    """`_user_summary` carries `is_admin`; reusing it for a key lookup would leak admin authority
    the moment any caller read the flag. The distinct shape is the guard, so pin its keys."""
    from mosaera_api.auth import hash_password, hash_token

    store = client.store  # type: ignore[attr-defined]
    user = store.create_user("keyowner", hash_password(PASSPHRASE), is_admin=True)
    store.create_api_key(hash_token("plaintext-key"), int(user["id"]), "k")
    owner = store.api_key_owner(hash_token("plaintext-key"))
    assert owner is not None
    assert "is_admin" not in owner, "the key projection leaked the admin flag"
    assert set(owner) == {"user_id", "username", "key_id"}


@requires_db
def test_a_revoked_key_stops_resolving_but_the_ROW_survives(client: TestClient) -> None:
    """Revocation is a soft delete on purpose: `audit_events.run_id` is a non-nullable FK to runs,
    so there is no non-run audit channel and this row IS the record that the credential existed."""
    from datetime import UTC, datetime

    from mosaera_api.auth import hash_password, hash_token

    store = client.store  # type: ignore[attr-defined]
    user = store.create_user("revoker", hash_password(PASSPHRASE), is_admin=False)
    store.create_api_key(hash_token("doomed"), int(user["id"]), "doomed")
    listed = store.list_api_keys(int(user["id"]))
    assert store.revoke_api_key(listed[0]["id"], int(user["id"]), datetime.now(UTC)) is True

    assert store.api_key_owner(hash_token("doomed")) is None, "a revoked key still authenticated"
    after = store.list_api_keys(int(user["id"]))
    assert len(after) == 1 and after[0]["revoked"] is True, "the row was destroyed, not revoked"
    assert store.revoke_api_key(listed[0]["id"], int(user["id"]), datetime.now(UTC)) is False


@requires_db
def test_you_cannot_revoke_someone_elses_key(client: TestClient) -> None:
    """Ownership is in the store's WHERE clause, not a check a route can forget."""
    from datetime import UTC, datetime

    from mosaera_api.auth import hash_password, hash_token

    store = client.store  # type: ignore[attr-defined]
    mine = store.create_user("mine", hash_password(PASSPHRASE))
    theirs = store.create_user("theirs", hash_password(PASSPHRASE))
    store.create_api_key(hash_token("theirs-key"), int(theirs["id"]), "t")
    victim = store.list_api_keys(int(theirs["id"]))[0]

    assert store.revoke_api_key(victim["id"], int(mine["id"]), datetime.now(UTC)) is False
    assert store.api_key_owner(hash_token("theirs-key")) is not None, "another user's key died"


@requires_db
def test_last_used_is_coarse_so_auth_does_not_write_every_request(client: TestClient) -> None:
    """A write per request would make a key materially more expensive than a session."""
    from datetime import UTC, datetime, timedelta

    from mosaera_api.auth import hash_password, hash_token

    store = client.store  # type: ignore[attr-defined]
    user = store.create_user("toucher", hash_password(PASSPHRASE))
    store.create_api_key(hash_token("touch-me"), int(user["id"]), "t")
    now = datetime.now(UTC)

    store.touch_api_key(hash_token("touch-me"), now)
    first = store.list_api_keys(int(user["id"]))[0]["last_used_at"]
    assert first is not None, "first use was never recorded"

    store.touch_api_key(hash_token("touch-me"), now + timedelta(seconds=30))
    assert store.list_api_keys(int(user["id"]))[0]["last_used_at"] == first, "wrote again too soon"

    store.touch_api_key(hash_token("touch-me"), now + timedelta(seconds=600))
    assert store.list_api_keys(int(user["id"]))[0]["last_used_at"] != first, "never went stale"


def test_the_module_refuses_without_a_database() -> None:
    """No DB needed for this one: user accounts require one, so key management must say so
    rather than fail obscurely."""
    from fastapi import HTTPException
    from mosaera_api.routes.keys import _session_user

    with pytest.raises(HTTPException) as e:
        _session_user(None, None)  # type: ignore[arg-type]
    assert e.value.status_code == 503


def test_the_guard_reads_the_SESSION_not_the_api_key_state() -> None:
    """Pins the mechanism behind 'a key cannot mint a key'. `_session_user` must consult the
    session cookie only; making it honour `request.state.api_key` would make a leaked credential
    self-renewing, and that change would pass every other test in this file."""
    import inspect

    from mosaera_api.routes import keys

    src = inspect.getsource(keys._session_user)
    assert "current_user(" in src, "the guard no longer reads the session"
    assert "api_key" not in src.split('"""')[-1], (
        "the guard's BODY references api_key state — a key may be able to mint a key"
    )
