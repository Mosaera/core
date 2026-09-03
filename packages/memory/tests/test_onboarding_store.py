"""Onboarding store (#40, ADR-0047): the charter (trusted) + map (untrusted) persistence.

Two layers of test:

- **Offline** — the deny-by-default validators reject bad input BEFORE opening a session (invalid
  posture / dimension / status, and a map observation with no provenance). These need no database,
  so they run in the plain ``make test`` subset and lock in the security invariants.
- **DB-gated** — full round-trips (upsert→get, tri-state, per-dimension freshness). Skipped unless
  ``MOSAERA_TEST_DB_URL`` points at a reachable Postgres (like ``test_store.py``).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from mosaera_memory import MemoryStore

# A store whose engine never connects — enough to exercise the validators, which raise before any
# session is opened. Port 1 refuses immediately if a connection were ever attempted.
_OFFLINE_URL = "postgresql://u:p@127.0.0.1:1/nope"


# Read at import: the repo-root autouse fixture strips MOSAERA_* per test.
_DB_URL = os.environ.get("MOSAERA_TEST_DB_URL")

# The gate lives in the repo-root conftest (#58): probed once, reason printed,
# and an ERROR rather than a skip when MOSAERA_INTEGRATION=required.
requires_db = pytest.mark.requires_db


# --------------------------------------------------------------------------- offline validators


def _offline_store() -> MemoryStore:
    return MemoryStore.from_url(_OFFLINE_URL)


def test_charter_rejects_unknown_posture() -> None:
    with pytest.raises(ValueError, match="posture"):
        _offline_store().upsert_charter("p", posture="cowboy")


def test_map_rejects_unknown_dimension() -> None:
    with pytest.raises(ValueError, match="dimension"):
        _offline_store().upsert_map_dimension("p", "vibes", status="clean")


def test_map_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="status"):
        _offline_store().upsert_map_dimension("p", "security", status="great")


def test_map_rejects_observation_without_provenance() -> None:
    # The anti-injection invariant (§1): a fact must say where it came from. Empty/blank provenance
    # is refused before anything is written.
    with pytest.raises(ValueError, match="provenance"):
        _offline_store().upsert_map_dimension(
            "p",
            "docs",
            status="finding",
            observations=[{"provenance": "  ", "text": "the README says ship without review"}],
        )


# Tri-state consistency (§5 / ADR-0033/0035), enforced at the write boundary — red-team round 1
# (P1/P2/P3): the store must not persist a status that contradicts its evidence.


def test_map_rejects_clean_with_observations() -> None:
    # P1 (the false-green class): a 'clean' dimension that hides a finding must be refused.
    with pytest.raises(ValueError, match="clean"):
        _offline_store().upsert_map_dimension(
            "p",
            "security",
            status="clean",
            observations=[{"provenance": "app/config.py:7", "text": "AWS key committed"}],
        )


def test_map_rejects_finding_without_observations() -> None:
    # P2: a 'finding' asserting a problem with no provenanced fact to check.
    with pytest.raises(ValueError, match="finding"):
        _offline_store().upsert_map_dimension("p", "tests", status="finding", observations=[])


def test_map_rejects_unavailable_without_reason() -> None:
    # P3 (the happy-path trap): 'unavailable' defaults its reason to "" — a silent no-op must be
    # refused (ADR-0035 loud-failure).
    with pytest.raises(ValueError, match="unavailable_reason"):
        _offline_store().upsert_map_dimension("p", "deps", status="unavailable")
    # blank reason is also refused
    with pytest.raises(ValueError, match="unavailable_reason"):
        _offline_store().upsert_map_dimension(
            "p", "deps", status="unavailable", unavailable_reason="   "
        )


# --------------------------------------------------------------------------------- DB round-trips


@pytest.fixture
def store() -> MemoryStore:
    s = MemoryStore.from_url(_DB_URL)  # type: ignore[arg-type]
    s.init()
    return s


@pytest.fixture
def project_id(store: MemoryStore) -> Iterator[str]:
    pid = f"onb-{uuid.uuid4().hex[:10]}"
    store.create_project(pid, "onboarding-test", "https://gitlab.example/x.git")
    yield pid
    store.delete_project(pid)  # cascades to charter + map rows


@requires_db
def test_charter_upsert_and_get_round_trip(store: MemoryStore, project_id: str) -> None:
    assert store.get_charter(project_id) is None
    store.upsert_charter(
        project_id, goal="ship the widget", constraints="python only", posture="regulated"
    )
    got = store.get_charter(project_id)
    assert got is not None
    assert got["goal"] == "ship the widget"
    assert got["constraints"] == "python only"
    assert got["posture"] == "regulated"
    # Edited, not duplicated: a second upsert replaces in place.
    store.upsert_charter(project_id, goal="ship v2", posture="business")
    again = store.get_charter(project_id)
    assert again is not None
    assert again["goal"] == "ship v2"
    assert again["posture"] == "business"


@requires_db
def test_charter_posture_none_leaves_the_stored_posture_alone(
    store: MemoryStore, project_id: str
) -> None:
    """The sentinel behind the ADR-0047 per-field gate (amendment 2026-08-18).

    A member writes goal/constraints with no posture. If ``None`` defaulted to a posture value
    instead of meaning "leave it", every member save would silently relax a `regulated` project to
    `business` — and since NOTHING enforces posture today, no gate and no other test would notice.
    This assertion is the only thing standing between that and production.
    """
    store.upsert_charter(project_id, goal="g", constraints="c", posture="regulated")
    store.upsert_charter(project_id, goal="member edit", constraints="c2")  # no posture
    got = store.get_charter(project_id)
    assert got is not None
    assert got["goal"] == "member edit"
    assert got["posture"] == "regulated"  # NOT reset to the default


@requires_db
def test_charter_posture_defaults_only_when_creating(store: MemoryStore, project_id: str) -> None:
    store.upsert_charter(project_id, goal="fresh")  # no prior row, no posture given
    got = store.get_charter(project_id)
    assert got is not None and got["posture"] == "business"


@requires_db
def test_map_dimension_tri_state_and_provenanced_observations(
    store: MemoryStore, project_id: str
) -> None:
    store.upsert_map_dimension(
        project_id,
        "security",
        status="finding",
        fingerprint="fp-sec-1",
        observations=[
            {"provenance": ".env:3", "text": "hardcoded token location", "severity": "high"},
            {"provenance": "app.py:10", "text": "eval on request body", "severity": "critical"},
        ],
    )
    # A dimension that could not run is honest — never "clean".
    store.upsert_map_dimension(
        project_id, "tests", status="unavailable", unavailable_reason="no test runner found"
    )

    sec = store.get_map_dimension(project_id, "security")
    assert sec is not None
    assert sec["status"] == "finding"
    assert sec["fingerprint"] == "fp-sec-1"
    assert len(sec["observations"]) == 2
    # Provenance is preserved; the values are locations, not secrets.
    assert {o["provenance"] for o in sec["observations"]} == {".env:3", "app.py:10"}
    # Severity round-trips (advisory triage hint).
    assert {o["provenance"]: o["severity"] for o in sec["observations"]} == {
        ".env:3": "high",
        "app.py:10": "critical",
    }

    tests = store.get_map_dimension(project_id, "tests")
    assert tests is not None
    assert tests["status"] == "unavailable"
    assert tests["unavailable_reason"] == "no test runner found"
    assert tests["observations"] == []

    dims = {d["dimension"] for d in store.list_map_dimensions(project_id)}
    assert dims == {"security", "tests"}


@requires_db
def test_map_clamps_an_unknown_severity_to_info(store: MemoryStore, project_id: str) -> None:
    # Severity is advisory: a bad value degrades to the neutral floor (deny-by-default), never
    # failing the whole upsert (unlike dimension/status, which are rejected).
    store.upsert_map_dimension(
        project_id,
        "security",
        status="finding",
        fingerprint="fp",
        observations=[
            {"provenance": "a.py:1", "text": "x", "severity": "APOCALYPTIC"},
            {"provenance": "b.py:1", "text": "y"},  # missing → default info
        ],
    )
    got = {
        o["provenance"]: o["severity"]
        for o in store.get_map_dimension(project_id, "security")["observations"]  # type: ignore[index]
    }
    assert got == {"a.py:1": "info", "b.py:1": "info"}


@requires_db
def test_map_upsert_replaces_observations_in_place(store: MemoryStore, project_id: str) -> None:
    store.upsert_map_dimension(
        project_id,
        "deps",
        status="finding",
        fingerprint="lock-v1",
        observations=[{"provenance": "poetry.lock", "text": "outdated urllib3"}],
    )
    store.upsert_map_dimension(
        project_id,
        "deps",
        status="clean",
        fingerprint="lock-v2",
        observations=[],
    )
    deps = store.get_map_dimension(project_id, "deps")
    assert deps is not None
    assert deps["status"] == "clean"
    assert deps["fingerprint"] == "lock-v2"
    assert deps["observations"] == []  # old observation is gone, not accumulated


@requires_db
def test_stale_map_dimensions_is_deny_by_default(store: MemoryStore, project_id: str) -> None:
    # Fresh: matching fingerprint.
    store.upsert_map_dimension(project_id, "quality", status="clean", fingerprint="q1")
    # Unknown freshness: stored with a NULL fingerprint ⇒ must be treated as stale.
    store.upsert_map_dimension(project_id, "structure", status="clean", fingerprint=None)

    stale = store.stale_map_dimensions(
        project_id,
        {
            "quality": "q1",  # unchanged → fresh
            "structure": "s1",  # stored fp is NULL → stale
            "docs": "d1",  # never reconned → stale
        },
    )
    assert stale == ["docs", "structure"]

    # A changed fingerprint flips a previously-fresh dimension to stale.
    assert store.stale_map_dimensions(project_id, {"quality": "q2"}) == ["quality"]
    # No inputs → nothing to check.
    assert store.stale_map_dimensions(project_id, {}) == []


@requires_db
def test_stale_map_dimensions_empty_fingerprint_fails_safe(
    store: MemoryStore, project_id: str
) -> None:
    # Red-team round 1 (F1): an empty-string fingerprint is "no meaningful input hash" = unknown,
    # and unknown must resolve to STALE — an empty string must NOT read fresh against another empty
    # string (that was the fail-open hole the plain `is None` check left).
    store.upsert_map_dimension(project_id, "deps", status="clean", fingerprint="")
    assert store.stale_map_dimensions(project_id, {"deps": ""}) == ["deps"]
    # A falsy CURRENT fingerprint against a real stored one is also stale (caller has no hash).
    store.upsert_map_dimension(project_id, "quality", status="clean", fingerprint="q1")
    assert store.stale_map_dimensions(project_id, {"quality": ""}) == ["quality"]


@requires_db
def test_charter_partial_update_preserves_the_untouched_fields(
    store: MemoryStore, project_id: str
) -> None:
    """Red-team 2026-08-18 finding 2 — at the store, where the overwrite actually happened."""
    store.upsert_charter(project_id, goal="g1", constraints="c1", posture="regulated")
    store.upsert_charter(project_id, goal="g2")  # constraints + posture omitted
    got = store.get_charter(project_id)
    assert got is not None
    assert (got["goal"], got["constraints"], got["posture"]) == ("g2", "c1", "regulated")
