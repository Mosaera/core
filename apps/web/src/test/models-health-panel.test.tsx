import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Preflight } from "../api/firstRun";
import { ModelsHealthPanel } from "../components/settings/models/ModelsHealthPanel";

const mocks = vi.hoisted(() => ({ preflight: vi.fn() }));

vi.mock("../api/firstRun", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/firstRun")>();
  return { ...mod, firstRunApi: { ...mod.firstRunApi, preflight: mocks.preflight } };
});

function pf(over: Partial<Preflight> = {}): Preflight {
  return {
    checks: [],
    inventory: { ollama_reachable: null, ollama_tags: [], ollama_error: "", env_keys: [] },
    can_run: true,
    reason: "",
    blocks_launch: false,
    ...over,
  };
}

function renderPanel() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ModelsHealthPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ModelsHealthPanel", () => {
  it("renders a backend check with its fix — including the embed model, folded into the Ollama row", async () => {
    mocks.preflight.mockResolvedValue(
      pf({
        checks: [
          {
            key: "backend.ollama",
            label: "Ollama models",
            status: "fail",
            ok: false,
            detail: "reachable, but not pulled: qwen3-coder:30b, nomic-embed-text",
            fix: "ollama pull qwen3-coder:30b && ollama pull nomic-embed-text",
          },
        ],
      }),
    );
    renderPanel();
    expect(await screen.findByText("Ollama models")).toBeInTheDocument();
    expect(screen.getByText(/not pulled: qwen3-coder:30b, nomic-embed-text/)).toBeInTheDocument();
    expect(screen.getByText("ollama pull qwen3-coder:30b && ollama pull nomic-embed-text")).toBeInTheDocument();
  });

  it("says nothing when there is nothing to check (no backend or environment rows)", async () => {
    mocks.preflight.mockResolvedValue(pf({ checks: [{ key: "database", label: "Database", status: "note", ok: true, detail: "no db", fix: "" }] }));
    // "database" is neither a backend.* nor an environment (docker/images/database — wait,
    // database IS an environment check) row; use a truly unrelated key to hit the empty case.
    mocks.preflight.mockResolvedValue(pf({ checks: [{ key: "unrelated", label: "x", status: "ok", ok: true, detail: "", fix: "" }] }));
    const { container } = renderPanel();
    await new Promise((r) => setTimeout(r, 0));
    expect(container.textContent).toBe("");
  });

  it("shows an honest error when the readiness check itself fails", async () => {
    mocks.preflight.mockRejectedValue(new Error("500"));
    renderPanel();
    expect(await screen.findByText(/couldn't check/i)).toBeInTheDocument();
  });
});
