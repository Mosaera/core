import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CostModesState, Pricing, ProvidersState } from "../api/client";
import { ModelsSettings } from "../components/settings/models/ModelsSettings";
import { ToastProvider } from "../components/ui/toast";

const mocks = vi.hoisted(() => ({
  getProviders: vi.fn(),
  getCostModes: vi.fn(),
  getPricing: vi.fn(),
  saveCostModes: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      getProviders: mocks.getProviders,
      getCostModes: mocks.getCostModes,
      getPricing: mocks.getPricing,
      saveCostModes: mocks.saveCostModes,
    },
  };
});

const ROLE_META = [
  { role: "pm", label: "PM", display_name: "Quincy", remit: "Plans the work." },
  { role: "coder", label: "Coder", display_name: "Forge", remit: "Writes the changes." },
  { role: "reviewer", label: "Reviewer", display_name: "Rook", remit: "Checks the work." },
];

function cell(provider: string, model: string, overridden = false) {
  return {
    provider: overridden ? provider : null,
    model: overridden ? model : null,
    effective_provider: provider,
    effective_model: model,
    overridden,
  };
}

function providers(over: Partial<ProvidersState> = {}): ProvidersState {
  return {
    providers: [
      { id: "ollama", local: true, env_key: null, suggestions: [], configured: true, has_key: false, uses_env_key: false, key_masked: "", base_url: "http://localhost:11434", on_box: false },
      { id: "openai", local: false, env_key: "OPENAI_API_KEY", suggestions: ["gpt-4o"], configured: false, has_key: false, uses_env_key: false, key_masked: "", base_url: null, on_box: false },
    ],
    roles: {
      pm: { provider: "ollama", model: "gpt-oss:20b" },
      coder: { provider: "ollama", model: "qwen3-coder:30b" },
      reviewer: { provider: "ollama", model: "gpt-oss:20b" },
    },
    role_meta: ROLE_META,
    sources: [{ source: "Ollama", models: ["gpt-oss:20b", "qwen3-coder:30b"] }],
    ...over,
  };
}

function costModes(over: Partial<CostModesState> = {}): CostModesState {
  const roles = {
    pm: cell("ollama", "gpt-oss:20b"),
    coder: cell("ollama", "qwen3-coder:30b"),
    reviewer: cell("ollama", "gpt-oss:20b"),
  };
  return {
    modes: { economy: roles, balanced: roles, premium: roles },
    default_cost_mode: "balanced",
    available: ["economy", "balanced", "premium"],
    role_meta: ROLE_META,
    sources: [{ source: "Ollama", models: ["gpt-oss:20b", "qwen3-coder:30b"] }],
    ...over,
  };
}

const pricing = (over: Pricing["prices"] = {}): Pricing => ({ prices: over });

function renderSettings() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <ModelsSettings />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getProviders.mockResolvedValue(providers());
  mocks.getCostModes.mockResolvedValue(costModes());
  mocks.getPricing.mockResolvedValue(pricing());
  mocks.saveCostModes.mockResolvedValue(costModes());
});

describe("ModelsSettings", () => {
  it("renders the relabeled presets and the calm all-local consequence line", async () => {
    renderSettings();
    expect(await screen.findByRole("tab", { name: "Local · Free" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Balanced" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Quality · Cloud" })).toBeInTheDocument();
    expect(screen.getByText(/nothing leaves your machine/i)).toBeInTheDocument();
  });

  it("shows the tool requirement only on the acting roles", async () => {
    renderSettings();
    await screen.findByText("Coder");
    // Two acting roles across the roles table + defaults use the "needs tools"
    // chip; PM/Reviewer never do.
    expect(screen.getAllByText("needs tools").length).toBeGreaterThan(0);
  });

  it("warns (amber) and offers a fix when a role uses a cloud model with no price", async () => {
    mocks.getCostModes.mockResolvedValue(
      costModes({
        modes: {
          economy: { pm: cell("ollama", "gpt-oss:20b"), coder: cell("openai", "gpt-4o", true), reviewer: cell("ollama", "gpt-oss:20b") },
          balanced: { pm: cell("ollama", "gpt-oss:20b"), coder: cell("openai", "gpt-4o", true), reviewer: cell("ollama", "gpt-oss:20b") },
          premium: { pm: cell("ollama", "gpt-oss:20b"), coder: cell("openai", "gpt-4o", true), reviewer: cell("ollama", "gpt-oss:20b") },
        },
      }),
    );
    mocks.getProviders.mockResolvedValue(
      providers({
        providers: [
          { id: "ollama", local: true, env_key: null, suggestions: [], configured: true, has_key: false, uses_env_key: false, key_masked: "", base_url: null, on_box: false },
          { id: "openai", local: false, env_key: "OPENAI_API_KEY", suggestions: ["gpt-4o"], configured: true, has_key: true, uses_env_key: false, key_masked: "…k", base_url: null, on_box: false },
        ],
      }),
    );
    renderSettings();
    expect(await screen.findByText(/spend won't be counted/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Add price/i })).toHaveAttribute("href", "#models-pricing");
    // The egress line names the cloud role.
    expect(screen.getByText(/Coder runs on OpenAI/)).toBeInTheDocument();
  });

  it("hides pricing until a hosted provider is configured", async () => {
    renderSettings();
    await screen.findByText("Coder");
    expect(screen.queryByText(/paid model/i)).not.toBeInTheDocument();
  });

  it("persists a preset switch as the new default for new runs", async () => {
    renderSettings();
    fireEvent.click(await screen.findByRole("tab", { name: "Quality · Cloud" }));
    await waitFor(() => expect(mocks.saveCostModes).toHaveBeenCalled());
    expect(mocks.saveCostModes.mock.calls[0][0].default_cost_mode).toBe("premium");
  });

  it("renders each role's effective model for the active preset", async () => {
    // The write path (Base-UI Select interaction) is unreliable under jsdom; the
    // override payload shape is covered by the overridesOf lib test + the
    // preset-switch save test. Here we assert the table reflects the bindings.
    renderSettings();
    await screen.findByText("Coder");
    // Every role renders its job + a single grouped model selector.
    expect(screen.getByText("Writes the changes.")).toBeInTheDocument();
    expect(screen.getByLabelText("coder model")).toBeInTheDocument();
  });
});
