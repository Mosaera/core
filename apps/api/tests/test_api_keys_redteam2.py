"""RED TEAM round 2 — the classes round 1 did not touch (ADR-0127).

Round 1 attacked authority (escalation, self-propagation, confusion). This round attacks the
credential's SURFACE: where it can leak, what a hostile name does, whether the caps and races hold,
and whether revocation is really immediate under concurrency.
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


# --- E: leakage ----------------------------------------------------------------------------------


@requires_db
def test_E1_the_key_is_never_echoed_back_in_an_error(client: TestClient) -> None:
    """A refusal that quotes the credential puts it in logs, proxies and screenshots."""
    _setup(client)
    client.cookies.clear()
    secret = "super-secret-value-abc123"
    for r in (
        client.get("/api/history", headers={"Authorization": f"Bearer {secret}"}),
        client.get(f"/api/history?token={secret}"),
    ):
        assert secret not in r.text, "the refusal echoed the presented credential"


@requires_db
def test_E2_a_created_key_is_not_stored_in_plaintext_anywhere(client: TestClient) -> None:
    """Read the table directly: if the plaintext is recoverable from the DB, hashing is theatre."""
    from sqlalchemy import text

    _setup(client)
    secret = client.post("/api/keys", json={"name": "leaky"}).json()["key"]
    store = client.store  # type: ignore[attr-defined]
    with store.session() as s:
        rows = list(s.execute(text("SELECT * FROM api_keys")))
    blob = " ".join(str(r) for r in rows)
    assert secret not in blob, "the plaintext key is in the database"


# --- F: hostile input ----------------------------------------------------------------------------


@requires_db
@pytest.mark.parametrize(
    "name",
    [
        "<script>alert(1)</script>",
        "'; DROP TABLE api_keys; --",
        "a" * 500,
        "🔑 emoji ключ",
        "line\nbreak\ttab",
    ],
)
def test_F1_a_hostile_name_is_stored_safely_and_the_table_survives(
    client: TestClient, name: str
) -> None:
    """`name` is operator-supplied and rendered in the UI. It must round-trip without executing,
    truncating unsafely, or taking the table with it."""
    _setup(client)
    r = client.post("/api/keys", json={"name": name})
    assert r.status_code == 200, r.text
    listed = client.get("/api/keys").json()["keys"]
    assert listed, "the table did not survive the name"
    assert len(listed[0]["name"]) <= 64, "the 64-char bound was not enforced"


@requires_db
def test_F2_the_key_cap_cannot_be_exceeded(client: TestClient) -> None:
    """The cap bounds accidental accumulation; a caller that can pass it can grow the table."""
    _setup(client)
    for i in range(20):
        assert client.post("/api/keys", json={"name": f"k{i}"}).status_code == 200
    over = client.post("/api/keys", json={"name": "one-too-many"})
    assert over.status_code == 409, f"the 21st key was issued ({over.status_code})"
    # ...and revoking frees exactly one slot, rather than the cap counting revoked rows forever.
    first = client.get("/api/keys").json()["keys"][-1]["id"]
    assert client.delete(f"/api/keys/{first}").status_code == 200
    assert client.post("/api/keys", json={"name": "now-ok"}).status_code == 200


# --- G: revocation under load --------------------------------------------------------------------


@requires_db
def test_G1_revocation_is_immediate_across_many_requests(client: TestClient) -> None:
    """No caching anywhere in the path: the request after the revoke must fail, not the tenth."""
    _setup(client)
    key = client.post("/api/keys", json={"name": "racy"}).json()["key"]
    key_id = client.get("/api/keys").json()["keys"][0]["id"]
    h = {"Authorization": f"Bearer {key}"}
    for _ in range(5):
        assert client.get("/api/history", headers=h).status_code == 200
    client.delete(f"/api/keys/{key_id}")
    client.cookies.clear()
    for _ in range(5):
        assert client.get("/api/history", headers=h).status_code == 401, "a revoked key answered"


@requires_db
def test_G2_double_revoke_is_idempotent_not_an_error_or_a_resurrection(client: TestClient) -> None:
    _setup(client)
    client.post("/api/keys", json={"name": "twice"})
    key_id = client.get("/api/keys").json()["keys"][0]["id"]
    assert client.delete(f"/api/keys/{key_id}").status_code == 200
    assert client.delete(f"/api/keys/{key_id}").status_code == 404
    assert client.get("/api/keys").json()["keys"][0]["revoked"] is True


# --- H: the ?token= spelling, which is a REAL exposure ------------------------------------------


@requires_db
def test_H1_the_query_spelling_works_and_is_therefore_a_logging_exposure(
    client: TestClient,
) -> None:
    """NOT a refusal test — a documented risk, asserted so it cannot change silently.

    ADR-0004 already names the cost: a `?token=` "leaks into logs and history". API keys inherit
    that spelling from the shared service token. It is kept because the spelling is what SSE and
    `<img>` need, and a key that worked for one caller and not another would be a trap.

    The residual is REAL and accepted: a key in a URL reaches access logs, proxies and browser
    history. It is bounded by the two properties that make a key weak — never admin, cannot mint —
    and by revocation being per-key and immediate. If this test ever fails because the spelling was
    removed, that is a HARDENING and the ADR should be updated rather than the test deleted.
    """
    _setup(client)
    key = client.post("/api/keys", json={"name": "url-borne"}).json()["key"]
    client.cookies.clear()
    assert client.get(f"/api/history?token={key}").status_code == 200, (
        "the query spelling stopped working — if deliberate, update ADR-0127's residual"
    )
