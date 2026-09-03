import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Pricing, ModelSource } from "../api/client";
import { PricingDisclosure } from "../components/settings/models/PricingDisclosure";

/** The operator must be able to enter prompt-caching rates.
 *
 * Live 2026-08-21 (run 20260821-153142): a cached Haiku run billed $0.0729 but REPORTED $0.2118
 * — 2.9x — because the only storable rate was [input, output], and `cost._rate` prices cache
 * buckets at the input rate for a 2-element entry. The whole caching saving was invisible in the
 * instrument built to show it. `.env.example` documented the 4-element form all along; the parser
 * dropped it and the UI could not express it.
 */

const sources: ModelSource[] = [{ source: "Anthropic", models: ["claude-haiku-4-5"] }];

function wrap(pricing: Pricing) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PricingDisclosure pricing={pricing} sources={sources} />
    </QueryClientProvider>,
  );
}

describe("pricing cache rates", () => {
  it("offers a cache-write and cache-read field per priced model", () => {
    wrap({ prices: { "claude-haiku-4-5": { input: 1, output: 5 } } });
    expect(screen.getByLabelText("cache write rate 1")).toBeTruthy();
    expect(screen.getByLabelText("cache read rate 1")).toBeTruthy();
  });

  it("shows configured cache rates rather than dropping them", () => {
    wrap({
      prices: {
        "claude-haiku-4-5": { input: 1, output: 5, cache_write: 1.25, cache_read: 0.1 },
      },
    });
    expect(screen.getByLabelText<HTMLInputElement>("cache write rate 1").value).toBe("1.25");
    expect(screen.getByLabelText<HTMLInputElement>("cache read rate 1").value).toBe("0.1");
  });

  it("leaves the fields blank when no cache rate is set, never showing 0", () => {
    // Blank and zero must stay distinguishable: zero would price every cache hit as free.
    wrap({ prices: { "gpt-oss:20b": { input: 0.15, output: 0.6, cache_write: null, cache_read: null } } });
    expect(screen.getByLabelText<HTMLInputElement>("cache write rate 1").value).toBe("");
    expect(screen.getByLabelText<HTMLInputElement>("cache read rate 1").value).toBe("");
  });
});
