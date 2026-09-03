"""The /api/settings/general contract: layering, admin gating, and profile provenance.

Split out of ``test_api.py`` (a grandfathered 5.7k-line file the size ratchet is working down)
when ADR-0122 extended the settings view. No graph is needed here — these routes read and write
config — so ``create_app()`` is constructed without a factory.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from mosaera_api.app import create_app


def test_general_settings_get_put_admin_gated_and_persists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    monkeypatch.delenv("MOSAERA_MAX_ITERATIONS", raising=False)
    c = TestClient(create_app())

    # GET is open; a fresh box reports the class defaults with source "default".
    view = c.get("/api/settings/general").json()["knobs"]
    assert view["max_iterations"] == {
        "value": 8,  # the class default (raised 3->8 2026-08-07); the assertion is on SOURCE
        "source": "default",
        "kind": "int",
        "env": "MOSAERA_MAX_ITERATIONS",
        "choices": None,
        "visibility": "developer",  # a mechanics knob: behind the disclosure, not on Core
        "effect": None,  # no profile owns max_iterations, so there is no sentence for it
        "derived_from": None,  # no profile is selected on a fresh box...
        "clamped_by": None,  # an ordinary knob carries no clamp...
    }
    # ...but a posture-forced one says so, so the UI stops presenting an inert toggle as a choice.
    assert view["tester_enabled"]["clamped_by"] == "autonomous_verified"
    # PUT is admin-gated.
    assert c.put("/api/settings/general", json={"values": {"max_iterations": 5}}).status_code == 403
    # With the admin token it persists; the view now sources it from "stored".
    r = c.put(
        "/api/settings/general",
        headers={"X-Mosaera-Admin": "adm1n"},
        json={"values": {"max_iterations": 5, "run_max_usd": 3.0, "stream_reasoning": False}},
    )
    assert r.status_code == 200
    k = r.json()["knobs"]
    assert k["max_iterations"]["value"] == 5 and k["max_iterations"]["source"] == "stored"
    assert k["run_max_usd"]["value"] == 3.0 and k["stream_reasoning"]["value"] is False
    # Negatives are rejected.
    assert (
        c.put(
            "/api/settings/general",
            headers={"X-Mosaera-Admin": "adm1n"},
            json={"values": {"run_max_usd": -1}},
        ).status_code
        == 400
    )
    # A fresh Settings picks up the stored value — takes effect next run, no restart.
    from mosaera_core.config import Settings

    assert Settings.from_env().max_iterations == 5

    # ADR-0122: selecting an intent profile derives the mechanics THROUGH the real route, and the
    # view says where the value came from. `max_iterations_ceiling` was never set by hand here, so
    # the profile supplies it; `max_iterations` WAS stored above and must keep winning.
    k = c.put(
        "/api/settings/general",
        headers={"X-Mosaera-Admin": "adm1n"},
        json={"values": {"effort_profile": "cautious"}},
    ).json()["knobs"]
    assert k["max_iterations_ceiling"] == {
        "value": 8,
        "source": "profile",
        "kind": "int",
        "env": "MOSAERA_MAX_ITERATIONS_CEILING",
        "choices": None,
        "visibility": "developer",
        # A knob a profile DOES own carries the sentence that says what it changes — the fix for
        # a summary that used to read `max_iterations_ceiling: 8` and predict nothing.
        "effect": "The hard ceiling on plan/fix loops, whatever else is configured",
        "derived_from": "effort_profile",
        "clamped_by": None,
    }
    assert k["max_iterations"]["value"] == 5 and k["max_iterations"]["source"] == "stored"
    # The profile reaches the engine's Settings, and never outranks the explicit setting.
    s = Settings.from_env()
    assert s.max_iterations_ceiling == 8 and s.max_iterations == 5
    # An out-of-set profile is refused (ADR-0005: enumerables are dropdowns on BOTH layers).
    assert (
        c.put(
            "/api/settings/general",
            headers={"X-Mosaera-Admin": "adm1n"},
            json={"values": {"effort_profile": "yolo"}},
        ).status_code
        == 400
    )


def test_general_settings_reports_a_rejected_field_instead_of_pretending_it_saved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """#task-9/S4: an unknown/blank field used to be silently dropped while the response still
    said "Saved". The good fields in the SAME patch now apply (200, not a blanket 400), and
    `rejected` names the one that did not, with why."""
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    c = TestClient(create_app())
    r = c.put(
        "/api/settings/general",
        headers={"X-Mosaera-Admin": "adm1n"},
        json={"values": {"max_iterations": 5, "not_a_real_knob": True}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["knobs"]["max_iterations"]["value"] == 5
    assert body["rejected"] == {"not_a_real_knob": "unknown setting"}

    # An empty patch, or one that applies cleanly, reports an EMPTY rejected map — the client's
    # "Saved" is unconditional on nothing being in it.
    clean = c.put(
        "/api/settings/general",
        headers={"X-Mosaera-Admin": "adm1n"},
        json={"values": {"max_iterations": 6}},
    )
    assert clean.json()["rejected"] == {}
