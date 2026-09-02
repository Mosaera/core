"""Deployment readiness over HTTP, and the launch refusal (#119).

The properties, in the order they matter:

1. **No secret ever crosses this surface.** It reports whether a key is present and whether the
   provider accepted it — never a value, and not even a masked hint.
2. **An unconfigured instance is refused at the door**, naming the cause and the fix, instead of
   accepting a run that fails somewhere downstream.
3. **The guard is network-free.** Found while building this: a reachability check on the launch
   path makes the whole suite pass or fail on whether the machine happens to be running Ollama,
   because the root conftest strips `MOSAERA_*` and every `from_env()` falls back to
   `localhost:11434`. That is an environment-dependent test suite, so the guard asks a
   configuration question instead.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_api import _client_with, _FakeProjectMemory


def _mem() -> Any:
    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    return mem


# --- the read ---------------------------------------------------------------------------


def test_preflight_reports_checks_the_inventory_and_one_verdict() -> None:
    body = _client_with(_mem()).get("/api/preflight?verify=false").json()
    assert body["checks"] and all(
        {"key", "label", "status", "ok", "detail", "fix"} <= set(c) for c in body["checks"]
    )
    assert "can_run" in body and "reason" in body
    assert "inventory" in body  # what was FOUND — the wizard leads with this, not a blank form


def test_blocks_launch_agrees_with_the_guard_that_actually_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The payload must not describe a control the server does not exercise.

    Seen live on a fresh instance (2026-08-24): with an unreachable local Ollama the banner read
    "Runs will be refused until it is" and the very next POST /runs was accepted and cloned. The
    banner reads its consequence from this field, so it is pinned against the guard's own answer
    rather than against `can_run`, which asks the wider reachability question on purpose.
    """
    client = _client_with(_mem())
    # Local binding, nothing reachable: NOT set-up-complete, but nothing is refused either.
    assert client.get("/api/preflight?verify=false").json()["blocks_launch"] is False

    _hosted_no_key(monkeypatch)  # a real configuration gap — this one the guard does refuse
    assert client.get("/api/preflight?verify=false").json()["blocks_launch"] is True


def test_no_secret_crosses_this_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    # Presence and acceptance are reportable; the value is not, and neither is a masked tail —
    # a hint is still a disclosure channel and this endpoint has no reason to open one.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SUPERSECRETVALUE")
    raw = _client_with(_mem()).get("/api/preflight?verify=false").text
    assert "SUPERSECRETVALUE" not in raw
    assert "sk-ant" not in raw


def test_an_unknown_check_is_not_reported_as_ok() -> None:
    # Deny-by-default on the two-state view the SPA renders.
    from mosaera_core.preflight import Check

    assert Check("k", "L", "unknown", "d").as_dict()["ok"] is False


# --- the launch refusal -----------------------------------------------------------------


def _hosted_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind a role to a hosted provider and make sure no key exists — the unconfigured instance."""
    import dataclasses

    from mosaera_core.config import Settings

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    real = Settings.from_env

    def _bound(*a: Any, **k: Any) -> Settings:
        return dataclasses.replace(real(*a, **k), role_providers={"coder": "anthropic"})

    monkeypatch.setattr(Settings, "from_env", staticmethod(_bound))


def test_an_unconfigured_instance_refuses_a_run_and_names_the_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hosted_no_key(monkeypatch)
    resp = _client_with(_mem()).post(
        "/api/runs", json={"repo": "some-repo", "task": "do the thing"}
    )
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "coder" in detail and "anthropic" in detail  # WHICH role, WHICH provider
    assert "mosaera doctor" in detail  # and how to find out more


def test_the_backlog_launch_is_refused_too(monkeypatch: pytest.MonkeyPatch) -> None:
    # The path the UI actually calls. Guarding only `POST /runs` would leave the product's own
    # launch button walking into the failure this exists to prevent.
    mem = _mem()
    item = mem.add_backlog_item("p1", "do the thing", position=0)
    _hosted_no_key(monkeypatch)
    resp = _client_with(mem).post(f"/api/projects/p1/backlog/{item}/run")
    assert resp.status_code == 503 and "anthropic" in resp.json()["detail"]


def test_a_configured_instance_is_not_refused() -> None:
    # The default binding is local, so a stock instance launches. If this ever starts failing, the
    # guard has become stricter than "is this set up at all", which is not its job.
    mem = _mem()
    item = mem.add_backlog_item("p1", "do the thing", position=0)
    assert _client_with(mem).post(f"/api/projects/p1/backlog/{item}/run").status_code == 201


def test_the_guard_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression that matters for CI.

    A reachability probe here made every launch test depend on whether the machine happened to be
    running Ollama — green on the dev box, red on a CI runner, and for a reason nothing in the
    failure would have named. The guard asks a configuration question, so it must not touch the
    network at all.
    """
    import httpx

    def _explode(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the launch guard must not make a network call")

    monkeypatch.setattr(httpx, "get", _explode)
    mem = _mem()
    item = mem.add_backlog_item("p1", "do the thing", position=0)
    assert _client_with(mem).post(f"/api/projects/p1/backlog/{item}/run").status_code == 201
