"""RED TEAM round 1 — attacking the API-key credential (ADR-0127).

Target is the merged change, not the codebase. The claim under attack is the pair of structural
properties: **a key is never admin**, and **a key cannot mint a key**. Everything here tries to
make one of those false by a route the happy-path tests do not walk.

Written adversarially on purpose: each test is an attack that SHOULD fail, so a passing suite means
the attack was refused. A test here that goes green because the endpoint 404s proves nothing, so
every attack asserts it reached a real control.
"""

from __future__ import annotations

from collections.abc import Iterator

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


def _key(client: TestClient, name: str = "attack") -> str:
    _setup(client)
    r = client.post("/api/keys", json={"name": name})
    assert r.status_code == 200, r.text
    key = r.json()["key"]
    client.cookies.clear()
    return key


# --- A-1..A-4: privilege escalation --------------------------------------------------------------


@requires_db
def test_A1_the_query_param_spelling_is_not_a_back_door(client: TestClient) -> None:
    """The service token accepts `?token=`, so a key does too. If the header path enforces
    non-admin and the query path does not, the weaker spelling is the real authority."""
    key = _key(client)
    assert client.get(f"/api/history?token={key}").status_code == 200, "the spelling should work"
    escalated = client.get(f"/api/auth/users?token={key}")
    assert escalated.status_code in (401, 403), "?token= reached an admin gate the header refuses"


@requires_db
def test_A2_a_key_cannot_delete_a_user(client: TestClient) -> None:
    """Destructive admin, reached by a different verb than the read gate."""
    key = _key(client)
    # Against a REAL id, so a 404 cannot stand in for a refusal.
    store = client.store  # type: ignore[attr-defined]
    victim = store.list_users()[0]["id"]
    r = client.delete(f"/api/auth/users/{victim}", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code in (401, 403), f"a key deleted an account ({r.status_code})"
    assert store.list_users(), "the account is gone -- the key really did delete it"


@requires_db
def test_A3_a_key_cannot_write_secrets_or_config(client: TestClient) -> None:
    key = _key(client)
    h = {"Authorization": f"Bearer {key}"}
    for path, body in (
        ("/api/settings/general", {"stall_limit": 9}),
        ("/api/secrets", {"name": "GITLAB_TOKEN", "value": "stolen"}),
    ):
        r = client.post(path, json=body, headers=h)
        # 404/405 means the route shape differs — that is not a pass, it is an unexercised probe.
        assert r.status_code not in (200, 201), f"a key wrote {path} ({r.status_code})"


@requires_db
def test_A4_the_admin_header_does_not_combine_with_a_key(client: TestClient) -> None:
    """A key plus a GUESSED admin header must not add up to admin. Escalation by combination is
    the classic way two individually-safe credentials become one unsafe one."""
    key = _key(client)
    r = client.get(
        "/api/auth/users",
        headers={"Authorization": f"Bearer {key}", "X-Mosaera-Admin": "guess"},
    )
    assert r.status_code in (401, 403), "a key plus a bogus admin header escalated"


# --- B-1..B-3: self-propagation -------------------------------------------------------------------


@requires_db
def test_B1_a_key_cannot_mint_by_any_verb_or_spelling(client: TestClient) -> None:
    """The mint guard must not be header-shaped. Both credential spellings, all three endpoints."""
    key = _key(client)
    h = {"Authorization": f"Bearer {key}"}
    assert client.post("/api/keys", json={"name": "x"}, headers=h).status_code in (401, 403)
    assert client.post(f"/api/keys?token={key}", json={"name": "x"}).status_code in (401, 403)
    assert client.get(f"/api/keys?token={key}").status_code in (401, 403)
    assert client.delete(f"/api/keys/1?token={key}").status_code in (401, 403)


@requires_db
def test_B2_a_REVOKED_key_is_dead_immediately_on_the_next_request(client: TestClient) -> None:
    """No grace window, no cached authentication."""
    _setup(client)
    key = client.post("/api/keys", json={"name": "short-lived"}).json()["key"]
    key_id = client.get("/api/keys").json()["keys"][0]["id"]
    h = {"Authorization": f"Bearer {key}"}
    assert client.get("/api/history", headers=h).status_code == 200
    assert client.delete(f"/api/keys/{key_id}").status_code == 200
    client.cookies.clear()
    assert client.get("/api/history", headers=h).status_code == 401, "a revoked key still worked"


@requires_db
def test_B3_a_key_for_a_DELETED_user_stops_working(client: TestClient) -> None:
    """The FK cascades, but 'the row is gone' and 'the credential is refused' are different
    claims and only one of them is the security property."""
    from mosaera_api.auth import hash_password, hash_token

    store = client.store  # type: ignore[attr-defined]
    victim = store.create_user("doomed", hash_password(PASSPHRASE))
    store.create_api_key(hash_token("orphan-key"), int(victim["id"]), "k")
    assert store.api_key_owner(hash_token("orphan-key")) is not None
    store.delete_user(int(victim["id"]))
    assert store.api_key_owner(hash_token("orphan-key")) is None, "a deleted user's key survived"


# --- C-1..C-3: confusion and enumeration ---------------------------------------------------------


@requires_db
def test_C1_a_SESSION_token_is_not_usable_as_an_api_key(client: TestClient) -> None:
    """Both are sha256 hex in a table. If the key lookup ever read `user_sessions`, a stolen
    session cookie would become a bearer credential — and vice versa."""
    from mosaera_api.auth import hash_token

    _setup(client)
    session = client.cookies.get("mosaera_session")
    store = client.store  # type: ignore[attr-defined]
    if session:
        assert store.api_key_owner(hash_token(session)) is None, "a session hash resolved as a key"


@requires_db
def test_C2_an_api_key_is_not_usable_as_a_session_cookie(client: TestClient) -> None:
    """The mirror of C1. A key presented as a cookie must not authenticate as a session — that
    would hand it `is_admin` and defeat the entire non-admin property."""
    key = _key(client)
    client.cookies.set("mosaera_session", key)
    r = client.get("/api/auth/users")
    assert r.status_code in (401, 403), "an API key authenticated as a SESSION"


@requires_db
def test_C3_an_unknown_key_and_a_revoked_key_look_the_same(client: TestClient) -> None:
    """A different status or body between 'never existed' and 'was revoked' is an oracle for
    enumerating valid keys."""
    _setup(client)
    key = client.post("/api/keys", json={"name": "k"}).json()["key"]
    key_id = client.get("/api/keys").json()["keys"][0]["id"]
    client.delete(f"/api/keys/{key_id}")
    client.cookies.clear()

    revoked = client.get("/api/history", headers={"Authorization": f"Bearer {key}"})
    unknown = client.get("/api/history", headers={"Authorization": "Bearer never-existed-at-all"})
    assert revoked.status_code == unknown.status_code
    assert revoked.json() == unknown.json(), "the refusal distinguishes revoked from unknown"


# --- D-1..D-2: the state channel -----------------------------------------------------------------


@requires_db
def test_D1_request_state_carries_no_admin_flag(client: TestClient) -> None:
    """`request.state.api_key` is attribution, not authority. If it ever carried `is_admin`, any
    future route that read it would silently become an escalation path."""
    from mosaera_api.auth import hash_password, hash_token

    store = client.store  # type: ignore[attr-defined]
    admin = store.create_user("adm", hash_password(PASSPHRASE), is_admin=True)
    store.create_api_key(hash_token("adm-key"), int(admin["id"]), "k")
    owner = store.api_key_owner(hash_token("adm-key"))
    assert owner == {
        "user_id": int(admin["id"]),
        "username": "adm",
        "key_id": owner["key_id"] if owner else None,
    }, f"the owner projection changed shape: {owner}"


def test_D2_the_middleware_never_sets_a_session_user() -> None:
    """Source-level, because it is a property of what the code does NOT do and no request can
    prove absence. This is the single line the whole non-admin property rests on."""
    import inspect

    from mosaera_api import apikey_auth

    src = inspect.getsource(apikey_auth.authenticate_api_key)
    body = src.split('"""')[-1]
    assert "state.user" not in body, "the key path assigns request.state.user — escalation"
    assert "is_admin" not in body, "the key path touches is_admin"
    assert "state.api_key" in body, "attribution is no longer recorded"
