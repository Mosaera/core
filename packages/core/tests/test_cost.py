"""Unit tests for LLM usage/cost accounting (deterministic; no model calls)."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from mosaera_core.cost import (
    CostMeter,
    TokenUsage,
    UsageCallback,
    load_prices,
    model_name_of,
    price_usd,
    usage_from_message,
)


def _msg(usage_metadata=None, response_metadata=None):
    return SimpleNamespace(usage_metadata=usage_metadata, response_metadata=response_metadata or {})


def test_usage_from_standard_usage_metadata() -> None:
    u = usage_from_message(_msg(usage_metadata={"input_tokens": 120, "output_tokens": 45}))
    assert u == TokenUsage(120, 45)
    assert u.total_tokens == 165


def test_usage_falls_back_to_ollama_response_metadata() -> None:
    u = usage_from_message(_msg(response_metadata={"prompt_eval_count": 300, "eval_count": 80}))
    assert u == TokenUsage(300, 80)


def test_usage_missing_counts_are_zero_never_invented() -> None:
    assert usage_from_message(_msg()) == TokenUsage()
    assert usage_from_message(_msg(usage_metadata={"input_tokens": None})) == TokenUsage(0, 0)


def test_model_name_from_metadata() -> None:
    assert model_name_of(_msg(response_metadata={"model": "qwen3-coder:30b"})) == "qwen3-coder:30b"
    assert model_name_of(_msg(response_metadata={})) == "unknown"


def test_load_prices_parses_json_and_tolerates_garbage() -> None:
    # A 2-element entry is normalized to the canonical 4 by repeating the INPUT rate for both
    # cache buckets — "this model has no cache rates", priced exactly as before. Zeroing them
    # would make cached input free and understate the bill.
    assert load_prices({"MOSAERA_MODEL_PRICES": '{"gpt-4o": [2.5, 10.0]}'}) == {
        "gpt-4o": (2.5, 10.0, 2.5, 2.5)
    }
    assert load_prices({"MOSAERA_MODEL_PRICES": "not json"}) == {}
    assert load_prices({}) == {}


def test_load_prices_accepts_the_four_rate_cache_form() -> None:
    assert load_prices({"MOSAERA_MODEL_PRICES": '{"claude": [3.0, 15.0, 3.75, 0.3]}'}) == {
        "claude": (3.0, 15.0, 3.75, 0.3)
    }
    # A length nobody defined is dropped rather than guessed at — a half-specified rate would
    # silently misprice every call to that model.
    assert load_prices({"MOSAERA_MODEL_PRICES": '{"x": [1.0, 2.0, 3.0]}'}) == {}
    assert load_prices({"MOSAERA_MODEL_PRICES": '{"x": ["a", "b"]}'}) == {}


def test_price_usd_local_model_is_free_known_model_charged() -> None:
    prices = {"gpt-4o": (2.5, 10.0)}  # $/1M tokens
    # local model absent from the table → free
    assert price_usd("qwen3-coder:30b", TokenUsage(1000, 1000), prices) == 0.0
    # 1M input @ $2.5 + 1M output @ $10 = $12.5
    assert price_usd("gpt-4o", TokenUsage(1_000_000, 1_000_000), prices) == 12.5


def test_meter_rollup_splits_by_agent_and_model() -> None:
    meter = CostMeter(prices={"gpt-4o": (2.5, 10.0)})
    meter.record("Reviewer", "gpt-4o", TokenUsage(1_000_000, 0))  # $2.5
    meter.record("Reviewer", "gpt-4o", TokenUsage(0, 100_000))  # $1.0
    meter.record("Coder", "qwen3-coder:30b", TokenUsage(500, 500))  # free
    roll = meter.rollup()
    # totals: tokens and $ kept separate
    assert roll["total_tokens"] == 1_101_000
    assert roll["calls"] == 3
    assert roll["usd"] == 3.5
    # by_model: gpt-4o priced, qwen free
    by_model = {m["model"]: m for m in roll["by_model"]}
    assert by_model["gpt-4o"]["calls"] == 2 and by_model["gpt-4o"]["usd"] == 3.5
    assert by_model["qwen3-coder:30b"]["usd"] == 0.0
    # by_agent: Reviewer carries the paid model's $, Coder is free
    by_agent = {a["agent"]: a for a in roll["by_agent"]}
    assert by_agent["Reviewer"]["usd"] == 3.5 and by_agent["Reviewer"]["total_tokens"] == 1_100_000
    assert by_agent["Coder"]["usd"] == 0.0 and by_agent["Coder"]["total_tokens"] == 1000


def test_usage_callback_attributes_to_agent_from_metadata() -> None:
    meter = CostMeter()
    cb = UsageCallback(meter)
    msg = AIMessage(
        content="",
        usage_metadata={"input_tokens": 200, "output_tokens": 60, "total_tokens": 260},
        response_metadata={"model": "gpt-oss:20b"},
    )
    # start callback carries the owning node via the checkpoint namespace →
    # a review subgraph call attributes to the Reviewer.
    cb.on_chat_model_start(
        {}, [[]], run_id="rid1", metadata={"langgraph_checkpoint_ns": "review:abc"}
    )
    cb.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg, text="")]]), run_id="rid1")
    roll = meter.rollup()
    assert roll["total_tokens"] == 260
    assert roll["by_model"][0]["model"] == "gpt-oss:20b"
    assert roll["by_agent"][0]["agent"] == "Reviewer"


def test_usage_callback_skips_zero_usage_and_never_raises() -> None:
    meter = CostMeter()
    cb = UsageCallback(meter)
    # A message with no usage is skipped; an empty result is a no-op.
    cb.on_llm_end(
        LLMResult(generations=[[ChatGeneration(message=AIMessage(content="x"), text="x")]])
    )
    cb.on_llm_end(LLMResult(generations=[]))
    assert meter.rollup()["total_tokens"] == 0


def test_seed_carries_prior_spend_across_restart() -> None:
    # A rehydrated run must NOT reset spend to zero — seed the meter from the last
    # persisted rollup so budget/hard-cap math (which reads rollup totals) continues.
    prior = {
        "input_tokens": 1000,
        "output_tokens": 200,
        "total_tokens": 1200,
        "usd": 0.5,
        "calls": 3,
        "det_ops": 7,
        "by_agent": [
            {
                "agent": "Coder",
                "input_tokens": 1000,
                "output_tokens": 200,
                "total_tokens": 1200,
                "usd": 0.5,
                "calls": 3,
            }
        ],
        "by_model": [
            {
                "model": "gpt",
                "input_tokens": 1000,
                "output_tokens": 200,
                "total_tokens": 1200,
                "usd": 0.5,
                "calls": 3,
            }
        ],
    }
    m = CostMeter(prices={"gpt": (1.0, 1.0)})
    m.seed(prior)
    # Fresh meter with only the baseline reports the prior totals.
    r0 = m.rollup()
    assert r0["total_tokens"] == 1200 and r0["calls"] == 3 and r0["usd"] == 0.5
    # New live spend accumulates ON TOP of the baseline (prior + new).
    m.record("Coder", "gpt", TokenUsage(input_tokens=500, output_tokens=100))
    r1 = m.rollup()
    assert r1["total_tokens"] == 1800  # 1200 prior + 600 new
    assert r1["calls"] == 4  # 3 prior + 1 new
    assert r1["usd"] == round(0.5 + 600 / 1_000_000, 6)  # prior $ + new $
    # Breakdown rows merge (baseline + live for the same agent/model key).
    coder = next(row for row in r1["by_agent"] if row["agent"] == "Coder")
    assert coder["total_tokens"] == 1800 and coder["calls"] == 4


def test_seed_none_is_a_noop() -> None:
    m = CostMeter(prices={})
    m.seed(None)
    m.record("Coder", "local", TokenUsage(input_tokens=10, output_tokens=5))
    assert m.rollup()["total_tokens"] == 15


# --- cache-aware accounting (hosted-API prerequisite) -------------------------------------------
# The premise, verified against langchain-anthropic 1.4.8 (`chat_models.py:2384-2391`) rather than
# assumed from documentation: by the time usage reaches us, `input_tokens` ALREADY INCLUDES the
# cached tokens. Every test below exists because the opposite assumption is the natural one and
# produces numbers that look plausible while being ~2x wrong.


def _anthropic_usage(input_tokens, output_tokens, **details):
    """A message shaped as langchain-anthropic emits it."""
    return _msg(
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "input_token_details": details,
        }
    )


def test_cache_tokens_are_read_from_input_token_details() -> None:
    u = usage_from_message(_anthropic_usage(10_000, 500, cache_read=8_000, cache_creation=1_000))
    assert (u.input_tokens, u.cache_read, u.cache_write) == (10_000, 8_000, 1_000)
    # The whole point: the cached tokens are a BREAKDOWN of the input, so only the remainder is
    # billed at the full rate.
    assert u.uncached_input == 1_000


def test_cache_write_reads_the_per_ttl_keys_when_present() -> None:
    """langchain-anthropic ZEROES `cache_creation` once the per-TTL keys are populated
    (`chat_models.py:2374-2382`). Reading only the generic key would report zero cache writes on
    exactly the responses that did the writing, and bill them at the full input rate."""
    u = usage_from_message(
        _anthropic_usage(
            5_000, 100, cache_read=0, cache_creation=0, ephemeral_5m_input_tokens=4_000
        )
    )
    assert u.cache_write == 4_000
    assert u.uncached_input == 1_000


def test_cached_input_is_charged_once_and_at_the_cache_rate() -> None:
    """A cached call must cost LESS. A test asserting only "some number" would pass under
    double-counting, which is the error this whole change exists to prevent."""
    u = usage_from_message(_anthropic_usage(10_000, 500, cache_read=8_000, cache_creation=1_000))
    prices = {"claude": (3.0, 15.0, 3.75, 0.30)}
    # 1_000 uncached @3 + 500 out @15 + 1_000 written @3.75 + 8_000 read @0.30 = $0.01665
    assert price_usd("claude", u, prices) == 0.01665
    # …and strictly cheaper than the same tokens priced as if nothing were cached.
    uncached_equivalent = price_usd("claude", TokenUsage(10_000, 500), prices)
    assert price_usd("claude", u, prices) < uncached_equivalent


def test_a_two_rate_model_prices_exactly_as_it_did_before() -> None:
    """Compatibility is the default: an operator's stored settings.json holds pairs."""
    u = usage_from_message(_anthropic_usage(10_000, 500, cache_read=8_000, cache_creation=1_000))
    legacy = price_usd("claude", u, {"claude": (3.0, 15.0)})
    assert legacy == price_usd("claude", TokenUsage(10_000, 500), {"claude": (3.0, 15.0)})


def test_details_exceeding_the_total_cannot_produce_a_negative_charge() -> None:
    u = TokenUsage(1_000, 0, cache_read=5_000, cache_write=5_000)
    assert u.uncached_input == 0
    assert price_usd("claude", u, {"claude": (3.0, 15.0, 0.0, 0.0)}) == 0.0


def test_ollama_usage_reports_no_cache_tokens() -> None:
    """Local models have no cache; inventing one would fake a hit rate."""
    u = usage_from_message(_msg(response_metadata={"prompt_eval_count": 300, "eval_count": 80}))
    assert (u.cache_read, u.cache_write) == (0, 0)


def test_rollup_exposes_cache_totals_so_a_hit_rate_is_readable() -> None:
    meter = CostMeter(prices={"claude": (3.0, 15.0, 3.75, 0.30)})
    meter.record("plan", "claude", TokenUsage(10_000, 500, cache_read=8_000, cache_write=1_000))
    roll = meter.rollup()
    assert roll["cache_read"] == 8_000 and roll["cache_write"] == 1_000
    assert roll["input_tokens"] == 10_000  # still the TOTAL input, cache included
    assert roll["by_model"][0]["cache_read"] == 8_000


# --- shadow spend: visible, never owed ----------------------------------------------------------


def test_shadow_models_are_priced_but_kept_out_of_usd() -> None:
    """The point of a shadow price is to make the burn VISIBLE before it is ever paid for
    (`roadmap.md:1285-1296`) — not to create a bill. `usd` is what `runner/_budget.py` caps on, so
    imputed dollars in it would park and cancel runs over money nobody spent."""
    meter = CostMeter(prices={"local:8b": (3.0, 15.0)}, shadow_models=frozenset({"local:8b"}))
    meter.record("coder", "local:8b", TokenUsage(1_000_000, 0))
    roll = meter.rollup()

    assert roll["usd"] == 0.0  # nothing is owed
    assert roll["shadow_usd"] == 3.0  # …and the burn is visible anyway
    assert roll["by_model"][0]["shadow"] is True


def test_real_and_shadow_spend_are_summed_separately() -> None:
    meter = CostMeter(
        prices={"local:8b": (3.0, 15.0), "claude": (3.0, 15.0)},
        shadow_models=frozenset({"local:8b"}),
    )
    meter.record("coder", "local:8b", TokenUsage(1_000_000, 0))
    meter.record("pm", "claude", TokenUsage(1_000_000, 0))
    roll = meter.rollup()

    assert (roll["usd"], roll["shadow_usd"]) == (3.0, 3.0)
    assert {r["model"]: r["shadow"] for r in roll["by_model"]} == {
        "local:8b": True,
        "claude": False,
    }


def test_no_shadow_set_means_every_dollar_is_real() -> None:
    """Default-empty, so every existing meter and every persisted rollup behaves as before."""
    meter = CostMeter(prices={"claude": (3.0, 15.0)})
    meter.record("pm", "claude", TokenUsage(1_000_000, 0))
    roll = meter.rollup()

    assert (roll["usd"], roll["shadow_usd"]) == (3.0, 0.0)


def test_prompt_eval_ms_is_read_when_ollama_ALSO_reports_usage_metadata() -> None:
    """The shape ChatOllama actually returns — and the one that made the first cut INERT.

    ChatOllama populates BOTH `usage_metadata` (LangChain standard) and `response_metadata` (its
    native fields, incl. `prompt_eval_duration`) — see langchain_ollama chat_models.py's own
    docstring example. Reading the duration only in the response_metadata FALLBACK made it dead
    code, because the standard branch always returns first. Live run 20260821-153142 reported
    `prompt_eval_ms: 0` on every local call as a result.

    The original test set `usage_metadata=None`, so it passed without ever exercising this path —
    a test green for the wrong reason, guarding nothing.
    """
    msg = SimpleNamespace(
        usage_metadata={"input_tokens": 8_000, "output_tokens": 120},
        response_metadata={
            "prompt_eval_count": 8_000,
            "eval_count": 120,
            "prompt_eval_duration": 2_500_000_000,  # ns
        },
    )
    u = usage_from_message(msg)
    assert (u.input_tokens, u.output_tokens) == (8_000, 120)
    assert u.prompt_eval_ms == 2_500


def test_ollama_prompt_eval_duration_is_captured_in_milliseconds() -> None:
    """The only observable signal for the LOCAL prefix cache.

    Token counts cannot show a local cache hit: Ollama's `prompt_eval_count` reports the whole
    context size of the request, not the tokens actually recomputed. So a hit and a miss produce
    identical token numbers, and the difference shows only in how long prompt evaluation took.
    Without this, `ollama_keep_alive` would be a change nobody could confirm does anything.
    """
    msg = SimpleNamespace(
        usage_metadata=None,
        response_metadata={
            "prompt_eval_count": 8_000,
            "eval_count": 120,
            "prompt_eval_duration": 2_500_000_000,  # ns
        },
    )
    u = usage_from_message(msg)
    assert (u.input_tokens, u.output_tokens) == (8_000, 120)
    assert u.prompt_eval_ms == 2_500


def test_prompt_eval_ms_is_zero_when_the_provider_does_not_report_it() -> None:
    # Hosted providers report cache_read instead; we never invent a number.
    msg = SimpleNamespace(
        usage_metadata={"input_tokens": 10, "output_tokens": 2}, response_metadata={}
    )
    assert usage_from_message(msg).prompt_eval_ms == 0


def test_prompt_eval_ms_sums_across_calls() -> None:
    a = TokenUsage(100, 10, prompt_eval_ms=400)
    b = TokenUsage(100, 10, prompt_eval_ms=50)  # a cache hit: same tokens, far less evaluation
    assert (a + b).prompt_eval_ms == 450
