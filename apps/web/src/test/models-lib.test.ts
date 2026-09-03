import { describe, expect, it } from "vitest";

import type { CostModesState, Pricing } from "../api/client";
import {
  egressConsequence,
  humanList,
  isLoopbackUrl,
  isNonChatModel,
  ollamaPullFix,
  overridesOf,
  presetLabel,
  priceChip,
  providerLabel,
  roleNeedsTools,
  roleWarning,
  type EffectiveBinding,
} from "../lib/models";

const pricing = (over: Record<string, { input: number; output: number }> = {}): Pricing => ({
  prices: over,
});

describe("presetLabel / providerLabel", () => {
  it("maps the three built-in modes to operator-facing names", () => {
    expect(presetLabel("economy")).toBe("Local · Free");
    expect(presetLabel("balanced")).toBe("Balanced");
    expect(presetLabel("premium")).toBe("Quality · Cloud");
  });
  it("titlecases an unknown (future server-added) mode", () => {
    expect(presetLabel("turbo")).toBe("Turbo");
  });
  it("labels providers with correct casing", () => {
    expect(providerLabel("openai")).toBe("OpenAI");
    expect(providerLabel("ollama")).toBe("Ollama");
    expect(providerLabel("anthropic")).toBe("Anthropic");
  });
});

describe("roleNeedsTools", () => {
  it("is true only for the acting roles (coder, tester)", () => {
    expect(roleNeedsTools("coder")).toBe(true);
    expect(roleNeedsTools("tester")).toBe(true);
    expect(roleNeedsTools("pm")).toBe(false);
    expect(roleNeedsTools("reviewer")).toBe(false);
    expect(roleNeedsTools("critic")).toBe(false);
    expect(roleNeedsTools("embeddings")).toBe(false);
  });
});

describe("humanList", () => {
  it("joins names as a readable clause", () => {
    expect(humanList(["Coder"])).toBe("Coder");
    expect(humanList(["Coder", "Reviewer"])).toBe("Coder & Reviewer");
    expect(humanList(["A", "B", "C"])).toBe("A, B & C");
  });
});

describe("priceChip", () => {
  it("local models are free", () => {
    expect(priceChip("qwen", true, pricing())).toEqual({ text: "free", tone: "free" });
  });
  it("a priced cloud model shows its rate", () => {
    expect(priceChip("gpt-4o", false, pricing({ "gpt-4o": { input: 2.5, output: 10 } }))).toEqual({
      text: "$2.5/$10 per M",
      tone: "paid",
    });
  });
  it("an unpriced cloud model reads 'no price'", () => {
    expect(priceChip("gpt-4o", false, pricing()).tone).toBe("unknown");
  });
});

describe("egressConsequence", () => {
  const local = new Set(["ollama"]);
  const bind = (role: string, label: string, provider: string): EffectiveBinding => ({
    role,
    label,
    provider,
    model: "m",
  });

  it("is calm when every role is local", () => {
    const e = egressConsequence(
      [bind("pm", "PM", "ollama"), bind("coder", "Coder", "ollama")],
      local,
    );
    expect(e.usesCloud).toBe(false);
    expect(e.text).toMatch(/nothing leaves your machine/i);
  });

  it("names the cloud roles and provider when a role escalates", () => {
    const e = egressConsequence(
      [bind("pm", "PM", "ollama"), bind("coder", "Coder", "openai")],
      local,
    );
    expect(e.usesCloud).toBe(true);
    expect(e.text).toMatch(/Coder runs on OpenAI/);
    expect(e.text).toMatch(/sent off-box/);
  });
});

describe("roleWarning", () => {
  it("flags a missing model", () => {
    expect(roleWarning("ollama", "", true, pricing())).toMatch(/No model/);
  });
  it("flags a cloud model with no price", () => {
    expect(roleWarning("openai", "gpt-4o", false, pricing())).toMatch(/spend won't be counted/);
  });
  it("is silent for a priced cloud model and for local", () => {
    expect(roleWarning("openai", "gpt-4o", false, pricing({ "gpt-4o": { input: 1, output: 2 } }))).toBeNull();
    expect(roleWarning("ollama", "qwen", true, pricing())).toBeNull();
  });
});

describe("overridesOf", () => {
  const cell = (provider: string, model: string, overridden: boolean) => ({
    provider: overridden ? provider : null,
    model: overridden ? model : null,
    effective_provider: provider,
    effective_model: model,
    overridden,
  });
  const state: CostModesState = {
    modes: {
      economy: { pm: cell("ollama", "a", false), coder: cell("openai", "gpt-4o", true) },
      balanced: { pm: cell("ollama", "a", false) },
    },
    default_cost_mode: "balanced",
    available: ["economy", "balanced"],
    role_meta: [],
    sources: [],
  };

  it("keeps only overridden cells, in the saveCostModes payload shape", () => {
    const out = overridesOf(state);
    expect(out.economy).toEqual({ coder: { provider: "openai", model: "gpt-4o" } });
    expect(out.balanced).toEqual({}); // nothing overridden → falls back to base
  });
});

describe("isLoopbackUrl", () => {
  it("accepts real loopback endpoints", () => {
    for (const url of [
      "http://localhost:8001/v1",
      "http://LOCALHOST:8001/v1",
      "http://127.0.0.1:8001/v1",
      "http://127.5.5.5:11434",
      "http://[::1]:8001/v1",
    ]) {
      expect(isLoopbackUrl(url), url).toBe(true);
    }
  });

  it("rejects hosts that only look like loopback", () => {
    // A substring/prefix match would wrongly pass these; the check parses the hostname.
    for (const url of [
      "http://127.0.0.1.evil.com/v1",
      "http://localhost.evil.com/v1",
      "http://evil.com/?redirect=127.0.0.1",
      "http://evil.com/127.0.0.1/v1",
      "https://api.openai.com/v1",
      "http://10.0.0.5:8001/v1",
      "http://192.168.1.20:8001",
      "http://127.0.0.999:8001",
      // Loopback in the USERINFO, not the host — the connection goes to evil.com.
      "http://127.0.0.1@evil.com/v1",
      "http://localhost@evil.com/v1",
      "http://localhost:8001@evil.com/v1",
      "http://0.0.0.0:8001/v1",
      "not a url",
      "",
    ]) {
      expect(isLoopbackUrl(url), url).toBe(false);
    }
    expect(isLoopbackUrl(null)).toBe(false);
    expect(isLoopbackUrl(undefined)).toBe(false);
  });
});

describe("isNonChatModel", () => {
  it("flags embedding/rerank models, case-insensitively", () => {
    expect(isNonChatModel("nomic-embed-text:latest")).toBe(true);
    expect(isNonChatModel("NOMIC-EMBED-TEXT")).toBe(true);
    expect(isNonChatModel("bge-reranker-v2-m3")).toBe(true);
  });

  it("does not flag an ordinary chat model", () => {
    expect(isNonChatModel("qwen3-coder:30b")).toBe(false);
    expect(isNonChatModel("gpt-oss:20b")).toBe(false);
  });
});

describe("ollamaPullFix", () => {
  it("is the exact copyable pull command", () => {
    expect(ollamaPullFix("qwen3-coder:30b")).toBe("ollama pull qwen3-coder:30b");
  });
});
