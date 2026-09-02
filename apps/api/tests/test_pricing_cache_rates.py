"""Prompt-cache rates must survive the round trip, or a caching model prices itself wrong.

Live 2026-08-21, run `20260821-153142-e8d73a`: the Haiku coder read 162,641 of its 192,553 input
tokens from cache (84.5%) and billed **$0.0729** — but the record REPORTED **$0.2118**, a 2.9x
overstatement, because the only rate that could reach the engine was `[input, output]` and
`cost._rate` prices cache buckets at the input rate for a 2-element entry. $0.2118 is exactly what
the run would have cost with no caching at all, so the entire saving was invisible in the very
instrument built to show it.

`.env.example` had documented `[input, output, cache_write, cache_read]` the whole time. Two things
made it unreachable: `parse_price_map` required `len == 2` and dropped a 4-element entry WHOLE —
leaving the model with no price, i.e. accounted as free — and the pricing UI had no cache fields.

Kept out of `test_api.py`: that file is a 5,600-line grandfathered module the size ratchet holds
shrink-only, so new coverage belongs beside the behaviour it pins rather than piled on top.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from mosaera_api.app import RunSubmit, create_app


def _fake_factory(req: RunSubmit, run_id: str) -> tuple[Any, dict[str, Any], dict[str, Any], None]:
    """A stub graph factory. These endpoints never submit a run, so no graph is needed — and a
    local stub keeps this module independent of `test_api`'s internals."""
    return object(), {"configurable": {"thread_id": run_id}}, {"task": req.task}, None


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> TestClient:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.delenv("MOSAERA_MODEL_PRICES", raising=False)
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    return TestClient(create_app(graph_factory=_fake_factory))


def test_cache_rates_survive_the_round_trip(client: TestClient) -> None:
    """Through `settings.json` and `parse_price_map` — the step that used to discard them."""
    body = {
        "prices": {
            "claude-haiku-4-5": {
                "input": 1.0,
                "output": 5.0,
                "cache_write": 1.25,
                "cache_read": 0.10,
            }
        }
    }
    saved = client.put("/api/pricing", json=body).json()["prices"]["claude-haiku-4-5"]
    assert saved == {"input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.10}
    # Re-READ, not just echoed back: a restart must not silently revert the model to unpriced.
    assert client.get("/api/pricing").json()["prices"]["claude-haiku-4-5"] == saved


def test_a_half_filled_cache_pair_is_ignored_rather_than_persisted(client: TestClient) -> None:
    # One rate without the other would store a 3-element entry, which `parse_price_map` drops
    # WHOLE — the model would lose its price entirely, not merely its cache rates. So the pair is
    # all-or-nothing, and the base rate always survives.
    body = {"prices": {"m": {"input": 1.0, "output": 5.0, "cache_write": 1.25}}}
    saved = client.put("/api/pricing", json=body).json()["prices"]["m"]
    assert saved == {"input": 1.0, "output": 5.0, "cache_write": None, "cache_read": None}


def test_unset_cache_rates_read_back_as_none_not_zero(client: TestClient) -> None:
    # The distinction is load-bearing: None means "bill cache at the input rate" (the long-standing
    # 2-rate behaviour), while 0.0 would price every cache hit as FREE and understate a real bill.
    body = {"prices": {"gpt-oss:20b": {"input": 0.15, "output": 0.60}}}
    saved = client.put("/api/pricing", json=body).json()["prices"]["gpt-oss:20b"]
    assert saved["cache_write"] is None and saved["cache_read"] is None
