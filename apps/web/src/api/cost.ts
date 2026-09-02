/** LLM usage + cost accounting shapes (mirrors `mosaera_core.cost`).
 *
 *  Split out of `client.ts` rather than grown inside it: that file is a grandfathered god-file on
 *  a shrink-only ratchet, whose rule is "shrink them, or split them, but do not raise the recorded
 *  size". `clarification.ts` is the precedent for an api-level type module.
 */

export interface CostBreakdownRow {
  agent?: string;
  model?: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  /** Cached input, a BREAKDOWN of input_tokens — never added on top of it. */
  cache_read?: number;
  cache_write?: number;
  usd: number;
  /** The model runs on this box: these dollars are imputed, not owed. */
  shadow?: boolean;
}

/** Per-run LLM usage + cost accounting (mosaera_core.cost). A local model costs $0 in `usd`
 *  even when a rate IS configured — its imputed cost lands in `shadow_usd` instead, so a shadow
 *  price makes the burn visible without inventing a bill the budget caps would enforce. */
export interface RunCost {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_read?: number;
  cache_write?: number;
  /** Real money owed to a provider. */
  usd: number;
  /** Imputed cost of on-box models. Shown, never spent. */
  shadow_usd?: number;
  calls: number;
  by_agent: CostBreakdownRow[];
  by_model: CostBreakdownRow[];
}


/** A per-model API rate, $ per 1M tokens. Cache rates are null when unset — NOT zero, which would
 *  price every cache hit as free; unset means cache tokens bill at the input rate, which
 *  OVERSTATES a cached run (measured 2026-08-21: $0.2118 reported vs $0.0729 billed). */
export interface PriceEntry {
  input: number;
  output: number;
  cache_write?: number | null;
  cache_read?: number | null;
}

export interface Pricing {
  prices: Record<string, PriceEntry>;
}
