"""LLM usage + cost accounting.

Deterministic-first (ADR-0002): this is plain accounting over what the model
layer already returns — no model calls, no heuristics beyond reading the
provider's own token counts. A ``UsageCallback`` attached to a run's LangGraph
config captures every nested model call (PM/coder/reviewer) at one point; a
``CostMeter`` rolls it up BY AGENT and BY MODEL plus a grand total, keeping
token usage and dollar cost as separate figures (local models are free, so $0
must never masquerade as a cost line). Prices come from a configurable rate
table.

Agent attribution: each call is tagged with its owning graph node (from the
LangGraph checkpoint namespace on the start callback), mapped to the agent —
PM (plan), Coder (implement/fix), Reviewer (review). Cost stays per model,
since rates are per model.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from mosaera_core.team import agent_by_node

_UNKNOWN_MODEL = "unknown"


@dataclass(frozen=True)
class TokenUsage:
    """Input/output token counts for one or more model calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    #: Cached input, as a BREAKDOWN of ``input_tokens`` — never in addition to it. Verified against
    #: langchain-anthropic 1.4.8 (`chat_models.py:2384-2391`), which states "Anthropic's
    #: `input_tokens` excludes cached tokens, so we manually add `cache_read` and `cache_creation`
    #: tokens to get the true total" and does exactly that before the value ever reaches us.
    #: Reading these as extra tokens would double-count and inflate the one number this accounting
    #: exists to make trustworthy, so the relationship is asserted by test, not assumed.
    cache_read: int = 0
    cache_write: int = 0
    #: Milliseconds Ollama spent EVALUATING the prompt. The only signal that shows whether the
    #: LOCAL prefix cache hit: `prompt_eval_count` reports the request's whole context size, not
    #: the tokens actually recomputed, so token counts are flat whether the cache hits or misses.
    #: A hit shows up as this collapsing while `input_tokens` stays put. Zero on hosted providers,
    #: which report `cache_read` instead.
    prompt_eval_ms: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def uncached_input(self) -> int:
        """Input billed at the full rate: the total minus what was cached.

        Clamped at zero — a provider that ever reports details exceeding the total must not produce
        a negative charge.
        """
        return max(0, self.input_tokens - self.cache_read - self.cache_write)

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read + other.cache_read,
            self.cache_write + other.cache_write,
            self.prompt_eval_ms + other.prompt_eval_ms,
        )


def _cache_tokens(details: Any) -> tuple[int, int]:
    """``(cache_read, cache_write)`` from a LangChain ``input_token_details`` mapping.

    `cache_write` is not simply `cache_creation`. When a response carries the per-TTL keys,
    langchain-anthropic ZEROES the generic key to avoid double counting
    (`chat_models.py:2374-2382`) and puts the real figure in `ephemeral_5m_input_tokens` /
    `ephemeral_1h_input_tokens`. Reading only the generic key would report zero cache writes on
    exactly the responses that did the writing, and price them at the full input rate.
    """
    if not isinstance(details, Mapping):
        return 0, 0
    ttl_keys = ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
    per_ttl = sum(int(details.get(k) or 0) for k in ttl_keys)
    return int(details.get("cache_read") or 0), per_ttl or int(details.get("cache_creation") or 0)


def usage_from_message(message: Any) -> TokenUsage:
    """Extract token usage from an AIMessage, provider-agnostically.

    Prefers the LangChain-standard ``usage_metadata`` (``input_tokens`` /
    ``output_tokens``); falls back to Ollama's ``response_metadata``
    (``prompt_eval_count`` / ``eval_count``). Missing counts are zero — we never
    invent numbers.
    """
    resp = getattr(message, "response_metadata", None)
    resp = resp if isinstance(resp, Mapping) else {}
    # Read the Ollama evaluation time INDEPENDENTLY of which branch supplies the token counts.
    # ChatOllama populates BOTH `usage_metadata` and `response_metadata`, so the standard branch
    # below always wins and anything read only in the fallback is dead code — which is exactly how
    # the first cut of this shipped inert, reporting 0 on every local call.
    eval_ms = int(resp.get("prompt_eval_duration") or 0) // 1_000_000  # ns -> ms
    meta = getattr(message, "usage_metadata", None)
    if isinstance(meta, Mapping):
        return TokenUsage(
            int(meta.get("input_tokens") or 0),
            int(meta.get("output_tokens") or 0),
            *_cache_tokens(meta.get("input_token_details")),
            prompt_eval_ms=eval_ms,
        )
    if resp:
        return TokenUsage(
            int(resp.get("prompt_eval_count") or 0),
            int(resp.get("eval_count") or 0),
            prompt_eval_ms=eval_ms,
        )
    return TokenUsage()


def model_name_of(message: Any, fallback: str = _UNKNOWN_MODEL) -> str:
    """The model that produced a message, from its response metadata."""
    resp = getattr(message, "response_metadata", None)
    if isinstance(resp, Mapping) and resp.get("model"):
        return str(resp["model"])
    meta = getattr(message, "response_metadata", None)
    if isinstance(meta, Mapping) and meta.get("model_name"):
        return str(meta["model_name"])
    return fallback


# Rate table: model name -> rates in $/1M tokens. Local models are absent → free. Override with
# MOSAERA_MODEL_PRICES (JSON), e.g. {"gpt-4o": [2.5, 10.0]}.
#
# Two forms, and the SHORT ONE STAYS VALID: `[input, output]` means "this model has no cache rates"
# and prices exactly as it always did. `[input, output, cache_write, cache_read]` adds the two
# Anthropic charges — a cache write costs ~1.25x input, a cache read ~0.1x. Compatibility is the
# default (CLAUDE.md): an operator's stored settings.json must not need editing for this change.
Rate = tuple[float, float, float, float]
#: What a caller may HAND US is any 2- or 4-element sequence — `Settings.model_prices` is still
#: typed as pairs, and stored settings.json entries are pairs. `_rate` normalizes at the point of
#: use, so widening here keeps every existing caller compiling and every stored value valid.
Prices = Mapping[str, Sequence[float]]


def _rate(values: Any) -> Rate | None:
    """A 2- or 4-element price entry as ``(input, output, cache_write, cache_read)``.

    A 2-element entry falls back to the INPUT rate for both cache figures, so a model priced the
    old way is charged exactly as before whether or not its provider reports cache tokens. Zeroing
    them instead would silently make cached input free and understate the bill.
    """
    if not isinstance(values, (list, tuple)) or len(values) not in (2, 4):
        return None
    try:
        nums = [float(v) for v in values]
    except (TypeError, ValueError):
        return None
    if len(nums) == 2:
        return (nums[0], nums[1], nums[0], nums[0])
    return (nums[0], nums[1], nums[2], nums[3])


def load_prices(env: Mapping[str, str] | None = None) -> dict[str, Rate]:
    raw = (env if env is not None else os.environ).get("MOSAERA_MODEL_PRICES", "")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    out: dict[str, Rate] = {}
    if isinstance(data, dict):
        for model, values in data.items():
            rate = _rate(values)
            if rate is not None:
                out[str(model)] = rate
    return out


def price_usd(model: str, usage: TokenUsage, prices: Prices) -> float:
    """Dollar cost of ``usage`` for ``model``; 0.0 when the model has no rate.

    Each input token is charged ONCE. `usage.input_tokens` already includes the cached tokens (see
    `TokenUsage`), so the cached buckets are priced at their own rates and only the remainder at
    the full input rate. Charging `input_tokens` AND the cache buckets would double-count — the
    error that would hide a caching win by inflating the very number meant to reveal it.
    """
    rate = _rate(prices.get(model))
    if rate is None:
        return 0.0
    return (
        usage.uncached_input * rate[0]
        + usage.output_tokens * rate[1]
        + usage.cache_write * rate[2]
        + usage.cache_read * rate[3]
    ) / 1_000_000


# Graph node -> agent label, for attributing model spend to a team member.
# The PM planning node calls the model directly; the coder and reviewer are
# create_agent subgraphs, so their calls surface under the OUTER node name
# (implement/fix, review) via the LangGraph checkpoint namespace. Derived from
# the agent registry (mosaera_core.team) so a new agent's nodes are attributed
# from ONE place.
_AGENT_BY_NODE = agent_by_node()


def agent_for_node(node: str | None) -> str:
    """Map a graph node to the agent that owns it (else the node name)."""
    if not node:
        return "unknown"
    return _AGENT_BY_NODE.get(node, node)


def _accumulate(
    bucket: dict[str, dict[str, Any]],
    key_field: str,
    key: str,
    usage: TokenUsage,
    usd: float,
    calls: int,
    shadow: bool = False,
) -> None:
    row = bucket.setdefault(
        key,
        {
            key_field: key,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            # A breakdown OF input_tokens, not an addition to it — so a hit rate is
            # cache_read / input_tokens and the totals still sum the way they always did.
            "cache_read": 0,
            "cache_write": 0,
            # Local-cache visibility (Ollama): see TokenUsage.prompt_eval_ms.
            "prompt_eval_ms": 0,
            "usd": 0.0,
            # A row's dollars are imputed, not owed — the model runs on this box.
            "shadow": shadow,
            "calls": 0,
        },
    )
    row["input_tokens"] += usage.input_tokens
    row["output_tokens"] += usage.output_tokens
    row["total_tokens"] += usage.total_tokens
    row["cache_read"] += usage.cache_read
    row["cache_write"] += usage.cache_write
    row["prompt_eval_ms"] += usage.prompt_eval_ms
    row["usd"] += usd
    row["calls"] += calls


def _finalize(bucket: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(bucket.values())
    for r in rows:
        r["usd"] = round(r["usd"], 6)
    rows.sort(key=lambda r: r["total_tokens"], reverse=True)
    return rows


def _merge_rows(bucket: dict[str, dict[str, Any]], key_field: str, rows: Any) -> None:
    """Fold a persisted rollup's breakdown rows (by_agent/by_model) into a live
    bucket, so a seeded baseline shows up in the breakdown as well as the totals."""
    if not isinstance(rows, list):
        return
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        usage = TokenUsage(
            int(r.get("input_tokens") or 0),
            int(r.get("output_tokens") or 0),
            int(r.get("cache_read") or 0),
            int(r.get("cache_write") or 0),
        )
        _accumulate(
            bucket,
            key_field,
            str(r.get(key_field) or "unknown"),
            usage,
            float(r.get("usd") or 0.0),
            int(r.get("calls") or 0),
        )


@dataclass
class CostMeter:
    """Thread-safe accumulator of model usage for a single run.

    Records each call keyed by (agent, model) so the rollup can break spend
    down BOTH by agent (who) and by model (what/how much it costs). The worker
    thread streams the graph while callbacks fire; ``rollup`` may be read
    concurrently by API handlers.
    """

    prices: Prices = field(default_factory=load_prices)
    #: Models served ON THIS BOX. Their dollars are IMPUTED, not owed — a shadow price exists to
    #: make the burn visible before it is ever paid for (`roadmap.md:1285-1296`), and money that
    #: was never spent must not be summed into `usd`, which is what the budget caps read
    #: (`runner/_budget.py:12-30`). Pricing local models would otherwise start parking and
    #: cancelling runs over imaginary spend. Empty by default: nothing is shadow unless a caller
    #: says so, so every existing rollup is unchanged.
    shadow_models: frozenset[str] = field(default_factory=frozenset)
    # (agent, model) -> [accumulated usage, call count]
    _entries: dict[tuple[str, str], list[Any]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    # A prior session's persisted rollup, folded into every rollup() so spend
    # survives a restart (a parked run that rehydrates must NOT reset to $0 —
    # otherwise a hard budget cap becomes re-askable). Set via seed().
    _baseline: dict[str, Any] | None = None

    @classmethod
    def for_settings(cls, settings: Any) -> CostMeter:
        """A meter for a run: the operator's rates, with on-box models marked as shadow spend.

        Built here rather than at the call site because `runner/_base.py` sits at the 500-line
        ceiling, and because "which models are imaginary money" is one decision that every future
        meter should inherit rather than re-derive.
        """
        from mosaera_core.models import on_box_models

        return cls(prices=settings.model_prices, shadow_models=on_box_models(settings))

    def seed(self, prior: dict[str, Any] | None) -> None:
        """Carry a prior session's persisted rollup across a restart so budget
        math (and the breakdowns) resume from the real spend, not zero."""
        if prior:
            with self._lock:
                self._baseline = prior

    def record(self, agent: str, model: str, usage: TokenUsage) -> None:
        with self._lock:
            cur = self._entries.get((agent, model))
            if cur is None:
                self._entries[(agent, model)] = [usage, 1]
            else:
                cur[0] = cur[0] + usage
                cur[1] += 1

    def rollup(self) -> dict[str, Any]:
        """JSON-safe summary: grand totals (tokens + $ kept separate) plus
        per-agent and per-model breakdowns. Any seeded baseline (prior session)
        is folded in so restart-resumed runs report cumulative spend."""
        with self._lock:
            entries = {k: (u, c) for k, (u, c) in self._entries.items()}
            baseline = self._baseline
        total = TokenUsage()
        total_usd = 0.0
        total_calls = 0
        by_agent: dict[str, dict[str, Any]] = {}
        by_model: dict[str, dict[str, Any]] = {}
        total_shadow = 0.0
        for (agent, model), (usage, calls) in entries.items():
            usd = price_usd(model, usage, self.prices)
            shadow = model in self.shadow_models
            total = total + usage
            if shadow:
                total_shadow += usd
            else:
                total_usd += usd
            total_calls += calls
            _accumulate(by_agent, "agent", agent, usage, usd, calls, shadow)
            _accumulate(by_model, "model", model, usage, usd, calls, shadow)
        if baseline:
            total = total + TokenUsage(
                int(baseline.get("input_tokens") or 0),
                int(baseline.get("output_tokens") or 0),
                int(baseline.get("cache_read") or 0),
                int(baseline.get("cache_write") or 0),
            )
            total_usd += float(baseline.get("usd") or 0.0)
            total_shadow += float(baseline.get("shadow_usd") or 0.0)
            total_calls += int(baseline.get("calls") or 0)
            _merge_rows(by_agent, "agent", baseline.get("by_agent"))
            _merge_rows(by_model, "model", baseline.get("by_model"))
        return {
            "input_tokens": total.input_tokens,
            "output_tokens": total.output_tokens,
            "total_tokens": total.total_tokens,
            "prompt_eval_ms": total.prompt_eval_ms,
            "cache_read": total.cache_read,
            "cache_write": total.cache_write,
            # REAL money owed to a provider — what the budget caps bound.
            "usd": round(total_usd, 6),
            # Imputed cost of the on-box models, kept strictly apart so it can be SHOWN without
            # ever being SPENT. Conflating the two is how a $0.00 run and a $12 run come to look
            # the same, and how an imaginary bill could cancel a local run.
            "shadow_usd": round(total_shadow, 6),
            "calls": total_calls,
            "by_agent": _finalize(by_agent),
            "by_model": _finalize(by_model),
        }


def role_calls(rollup: Mapping[str, Any] | None, role: str) -> int:
    """How many model calls ``role`` actually made, from a finished run's rollup.

    **Did the producer speak?** — the question nobody was asking, and the reason 45 stored
    scorecards hold an outcome from a run whose escalated role never answered (measured
    2026-08-10). An escalation to an unreachable cloud tier fails every call, contributes nothing,
    and the bench then records that attempt *in place of* the tier-0 result it overwrote. ``error``
    stays None and ``escalation_path`` still names the model, so a failed escalation is
    indistinguishable from *"a stronger model tried and could not"* — the reading that produced
    three wrong conclusions in one session.

    Reachability cannot be established beforehand: a *priced* model (which
    ``models.cloud_tier_allowed`` checks, correctly, so the USD cap can bound the spend) may still
    be unfunded, revoked or misspelled. The honest signal is therefore post-hoc — and it already
    exists, because a role with zero successful calls contributes no ``by_agent`` row at all.

    The label comes from ``team.spec_for`` — the same ``AgentSpec.label`` that ``agent_by_node``
    attributes spend with — so this cannot drift from the thing it reads. An unknown role returns 0.
    """
    from mosaera_core.team import spec_for

    spec = spec_for(role)
    if spec is None:
        return 0
    for row in (rollup or {}).get("by_agent") or []:
        if isinstance(row, Mapping) and row.get("agent") == spec.label:
            return int(row.get("calls") or 0)
    return 0


def _node_from_metadata(metadata: Any) -> str | None:
    """The owning graph node for a model call. Prefer the checkpoint namespace's
    outermost segment (so a coder/reviewer subgraph call attributes to
    implement/review, not the generic inner node), else the node itself."""
    if not isinstance(metadata, Mapping):
        return None
    ns = metadata.get("langgraph_checkpoint_ns")
    if isinstance(ns, str) and ns:
        return ns.split("|", 1)[0].split(":", 1)[0] or None
    node = metadata.get("langgraph_node")
    return str(node) if node else None


class UsageCallback(BaseCallbackHandler):
    """Records every model call's usage into a ``CostMeter``, attributed to the
    agent (graph node) that made it.

    Attach to a run's LangGraph config (``config['callbacks']``); LangGraph
    propagates it to all nested model calls, so one attachment covers the whole
    PM/coder/reviewer pipeline. The owning node comes from the *start* callback's
    metadata (correlated to the *end* by run id). Best-effort: a malformed
    result never breaks a run.
    """

    def __init__(self, meter: CostMeter) -> None:
        self._meter = meter
        self._node: dict[Any, str] = {}
        self._lock = threading.Lock()

    def _remember(self, run_id: Any, metadata: Any) -> None:
        node = _node_from_metadata(metadata)
        if node and run_id is not None:
            with self._lock:
                self._node[run_id] = node

    def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:
        self._remember(kwargs.get("run_id"), kwargs.get("metadata"))

    def on_llm_start(self, serialized: Any, prompts: Any, **kwargs: Any) -> None:
        self._remember(kwargs.get("run_id"), kwargs.get("metadata"))

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            with self._lock:
                node = self._node.pop(kwargs.get("run_id"), None)
            agent = agent_for_node(node)
            for batch in response.generations:
                for gen in batch:
                    message = getattr(gen, "message", None)
                    if message is None:
                        continue
                    usage = usage_from_message(message)
                    if usage.total_tokens == 0:
                        continue
                    self._meter.record(agent, model_name_of(message), usage)
        except Exception:  # noqa: S110 — accounting must never break a run
            pass
