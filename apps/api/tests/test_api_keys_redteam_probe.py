"""Did round 1's attacks actually REACH a control, or pass because the route was not there?

A 404 satisfies "not 200" and an absent cookie satisfies `if session:`. Both would make an attack
green while proving nothing — the green-by-vacancy shape this repo has a name for. This probe
prints what each attacked path actually returns to an ADMIN SESSION, so an attack that never met a
gate is visible rather than counted as a refusal.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from test_auth import _fake_factory, _fresh_store, _setup, requires_db


@pytest.fixture
def client() -> Iterator[TestClient]:
    from mosaera_api.app import create_app

    store = _fresh_store()
    c = TestClient(create_app(graph_factory=_fake_factory, memory=store))
    c.store = store  # type: ignore[attr-defined]
    yield c
    for u in store.list_users():
        store.delete_user(u["id"])


@requires_db
def test_every_attacked_admin_path_EXISTS(client: TestClient) -> None:
    """As an authenticated ADMIN, each attacked path must NOT 404/405. If it does, the matching
    attack in round 1 was refused by routing rather than by authorization."""
    _setup(client)  # a real admin session
    # A REAL user id: 999 returns 404 from a route that DOES exist, which reads identically to a
    # missing route and sent the first version of this probe chasing the wrong defect.
    other = client.store.create_user("probe-victim", "x")  # type: ignore[attr-defined]
    probes = [
        ("GET", "/api/auth/users", None),
        ("DELETE", f"/api/auth/users/{other['id']}", None),
        ("PUT", "/api/settings/general", {"values": {"stall_limit": 9}}),
        ("POST", "/api/features/delete-tool", {"enabled": False}),
        ("POST", "/api/gitlab/config", {"url": "https://x.test", "token": "t"}),
    ]
    missing = []
    for method, path, body in probes:
        r = client.request(method, path, json=body)
        if r.status_code in (404, 405):
            missing.append(f"{method} {path} -> {r.status_code}")
    assert not missing, (
        "these attacked paths do not exist, so the round-1 attacks against them proved "
        f"NOTHING: {missing}"
    )


@requires_db
def test_the_session_cookie_name_is_what_the_attacks_assume(client: TestClient) -> None:
    """C1/C2 hinge on the cookie's name. A wrong name makes C1's `if session:` a no-op and C2 sets
    a cookie the server ignores — two attacks quietly testing nothing."""
    from mosaera_api.auth import SESSION_COOKIE

    _setup(client)
    assert SESSION_COOKIE == "mosaera_session", (
        f"the attacks hardcode 'mosaera_session' but the real cookie is {SESSION_COOKIE!r}"
    )
    assert client.cookies.get(SESSION_COOKIE), "login set no session cookie — C1 tested nothing"


@requires_db
def test_an_admin_SESSION_can_actually_do_the_thing_the_key_was_refused(client: TestClient) -> None:
    """The control test for the whole round. If an admin session ALSO cannot read the user list,
    then 'the key was refused' says nothing about keys — the endpoint is simply shut."""
    _setup(client)
    allowed = client.get("/api/auth/users")
    assert allowed.status_code == 200, (
        f"an admin SESSION could not read /api/auth/users ({allowed.status_code}), so refusing a "
        "key there demonstrates nothing about the key"
    )
