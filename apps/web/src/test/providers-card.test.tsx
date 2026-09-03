import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Provider } from "../api/client";
import { ProviderCard } from "../components/settings/models/ProviderCard";
import { ToastProvider } from "../components/ui/toast";

const mocks = vi.hoisted(() => ({
  saveProviders: vi.fn(),
  testProvider: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: { ...mod.api, saveProviders: mocks.saveProviders, testProvider: mocks.testProvider },
  };
});

function provider(over: Partial<Provider> = {}): Provider {
  return {
    id: "openai",
    local: false,
    env_key: "OPENAI_API_KEY",
    suggestions: ["gpt-4o"],
    configured: false,
    has_key: false,
    uses_env_key: false,
    key_masked: "",
    base_url: null,
    on_box: false,
    ...over,
  };
}

function renderCard(p = provider()) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <ProviderCard provider={p} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.saveProviders.mockResolvedValue({});
  mocks.testProvider.mockResolvedValue({ ok: true, count: 2, models: ["gpt-5", "gpt-5-mini"] });
});

describe("ProviderCard", () => {
  it("tests a key and reports the live model count", async () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /connect/i }));
    fireEvent.change(screen.getByLabelText("openai API key"), { target: { value: "sk-live" } });
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
    await waitFor(() => expect(mocks.testProvider).toHaveBeenCalledWith("openai", "sk-live", undefined));
    // Shown both as the status-dot label and the inline result line.
    expect((await screen.findAllByText(/2 models loaded/)).length).toBeGreaterThan(0);
  });

  it("shows an inline error when the key is rejected", async () => {
    mocks.testProvider.mockResolvedValue({ ok: false, count: 0, models: [], error: "invalid API key" });
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /connect/i }));
    fireEvent.change(screen.getByLabelText("openai API key"), { target: { value: "bad" } });
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
    expect((await screen.findAllByText(/invalid API key/)).length).toBeGreaterThan(0);
  });

  it("saves the key (write-only payload)", async () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /connect/i }));
    fireEvent.change(screen.getByLabelText("openai API key"), { target: { value: "sk-test" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mocks.saveProviders).toHaveBeenCalledTimes(1));
    expect(mocks.saveProviders.mock.calls[0][0].providers.openai.api_key).toBe("sk-test");
  });

  it("shows a saved-key hint and never a raw key", () => {
    renderCard(provider({ configured: true, has_key: true, key_masked: "…cret" }));
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    const keyInput = screen.getByLabelText("openai API key") as HTMLInputElement;
    expect(keyInput.placeholder).toContain("…cret");
    expect(keyInput.value).toBe("");
  });

  it("only allows the on-box declaration for a loopback endpoint", async () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /connect/i }));
    const box = screen.getByLabelText("openai runs on this machine") as HTMLInputElement;
    // No base URL yet → the declaration is unavailable, and says why.
    expect(box.disabled).toBe(true);
    expect(screen.getByText(/needs a loopback base URL/i)).toBeInTheDocument();
    // A hosted endpoint keeps it unavailable.
    fireEvent.change(screen.getByLabelText("openai base URL"), {
      target: { value: "https://api.openai.com/v1" },
    });
    expect((screen.getByLabelText("openai runs on this machine") as HTMLInputElement).disabled).toBe(true);
    // A loopback endpoint unlocks it, and it saves.
    fireEvent.change(screen.getByLabelText("openai base URL"), {
      target: { value: "http://localhost:8001/v1" },
    });
    fireEvent.click(screen.getByLabelText("openai runs on this machine"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mocks.saveProviders).toHaveBeenCalledTimes(1));
    expect(mocks.saveProviders.mock.calls[0][0].providers.openai).toMatchObject({
      base_url: "http://localhost:8001/v1",
      on_box: true,
    });
  });

  it("drops a stale on-box declaration when repointed off-box", async () => {
    // Saved as on-box, then repointed at a hosted URL: the payload must clear the flag
    // rather than send a contradiction the server would 422 (ADR-0024).
    renderCard(provider({ configured: true, base_url: "http://localhost:8001/v1", on_box: true }));
    fireEvent.click(screen.getByRole("button", { name: /edit/i }));
    fireEvent.change(screen.getByLabelText("openai base URL"), {
      target: { value: "https://api.openai.com/v1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mocks.saveProviders).toHaveBeenCalledTimes(1));
    expect(mocks.saveProviders.mock.calls[0][0].providers.openai.on_box).toBe(false);
  });

  it("renders Ollama as a local card with no key form", async () => {
    renderCard(provider({ id: "ollama", local: true, configured: true }));
    expect(screen.getByText(/local · \$0/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /connect/i })).not.toBeInTheDocument();
    // #119/M1 + O5: a local provider is PROBED (via the same POST /providers/test its Test
    // gate uses), not asserted "always on" — settle the mount probe before the test ends.
    await waitFor(() => expect(mocks.testProvider).toHaveBeenCalledWith("ollama"));
  });

  it("O5: probes a local provider truthfully — green/red/amber, never a fabricated always-on", async () => {
    mocks.testProvider.mockResolvedValue({ ok: true, count: 2, models: ["gpt-oss:20b", "qwen3-coder:30b"] });
    const { unmount } = renderCard(provider({ id: "ollama", local: true, configured: true }));
    await waitFor(() => expect(mocks.testProvider).toHaveBeenCalledWith("ollama"));
    expect(await screen.findByText(/2 models/)).toBeInTheDocument();
    unmount();

    mocks.testProvider.mockResolvedValue({ ok: false, count: 0, models: [], error: "not reachable at :11434" });
    const down = renderCard(provider({ id: "ollama", local: true, configured: true }));
    expect(await screen.findByText(/not reachable/)).toBeInTheDocument();
    down.unmount();
  });

  it("O5: amber when Ollama is reachable but a role's bound model isn't served", async () => {
    mocks.testProvider.mockResolvedValue({ ok: true, count: 1, models: ["gpt-oss:20b"] });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ToastProvider>
          <ProviderCard
            provider={provider({ id: "ollama", local: true, configured: true })}
            boundModels={["gpt-oss:20b", "qwen3-coder:30b"]}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/missing qwen3-coder:30b/)).toBeInTheDocument();
  });
});
