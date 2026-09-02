import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CostEstimate } from "../api/client";
import { RunPreviewCard } from "../components/backlog/RunPreviewCard";

const mocks = vi.hoisted(() => ({ estimate: vi.fn() }));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, estimate: mocks.estimate } };
});

function wrap(node: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {node}
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("RunPreviewCard estimate", () => {
  it("shows the conditioned per-mode projection when history exists", async () => {
    const est: CostEstimate = {
      cost_mode: "premium",
      available: true,
      runs_metered: 3,
      projected_usd: 0.25,
      per_role: [],
    };
    mocks.estimate.mockResolvedValue(est);
    wrap(<RunPreviewCard mode="guided" projectId="p1" costMode="premium" />);
    expect(await screen.findByText(/~\$0\.2500/)).toBeInTheDocument();
    expect(screen.getByText(/from 3 past runs/i)).toBeInTheDocument();
  });

  it("falls back to an honest 'no projection yet' when there's no history", async () => {
    mocks.estimate.mockResolvedValue({
      cost_mode: "balanced",
      available: false,
      runs_metered: 0,
    } satisfies CostEstimate);
    wrap(<RunPreviewCard mode="guided" projectId="p1" costMode="balanced" />);
    expect(await screen.findByText(/No cost projection yet/i)).toBeInTheDocument();
  });
});
