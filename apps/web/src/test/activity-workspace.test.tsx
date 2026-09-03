import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ActivityEvent, Project } from "../api/client";
import { ActivityWorkspace } from "../components/activity/ActivityWorkspace";

const mocks = vi.hoisted(() => ({ activity: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, activity: mocks.activity } };
});

function ev(over: Partial<ActivityEvent>): ActivityEvent {
  return {
    run_id: "r1",
    event: "node",
    detail: "test",
    created_at: "2026-07-08T10:00:00Z",
    task: "Build the thing\n\nThe hero section must render a headline and a CTA.\n\nAcceptance criteria: the CTA links to /signup.",
    ...over,
  };
}

function renderWs() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <ActivityWorkspace project={{ id: "p1" } as Project} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.activity.mockResolvedValue({
    events: [
      ev({ event: "run.error", detail: "XML" }),
      ev({ event: "node", detail: "review" }),
      ev({ event: "auto-park", detail: "validation_failed" }),
      ev({ event: "mr.opened", detail: "http://mr" }),
    ],
  });
});

describe("ActivityWorkspace", () => {
  it("groups events by run (collapsed + summarized) and expands to the detail", async () => {
    renderWs();
    // Collapsed: the run group shows the task + an outcome headline, not the noise.
    const header = await screen.findByRole("button", { name: /Build the thing/ });
    expect(screen.getByText("errored")).toBeInTheDocument(); // headline — run.error present
    expect(screen.queryByText(/Run errored/)).not.toBeInTheDocument(); // events hidden while collapsed
    // Expand → the governed steps, persona attribution, and a link to the run.
    fireEvent.click(header);
    expect(screen.getByText(/Run errored/)).toBeInTheDocument();
    expect(screen.getByText("The Tribune")).toBeInTheDocument(); // node review → Rook persona
    expect(screen.getByText(/Run errored/).closest("a")).toHaveAttribute(
      "href",
      "/projects/p1/history/r1",
    );
  });

  it("search jumps straight to a matching event (auto-expanded, non-matches hidden)", async () => {
    renderWs();
    await screen.findByRole("button", { name: /Build the thing/ });
    fireEvent.change(screen.getByLabelText("Search events"), { target: { value: "parked" } });
    expect(screen.getByText(/parked the run/)).toBeInTheDocument();
    expect(screen.queryByText(/Run errored/)).not.toBeInTheDocument();
  });

  it("filters by kind", async () => {
    renderWs();
    await screen.findByRole("button", { name: /Build the thing/ });
    fireEvent.click(screen.getByRole("tab", { name: "Merge" }));
    fireEvent.click(screen.getByRole("button", { name: /Build the thing/ }));
    expect(screen.getByText(/merge request/)).toBeInTheDocument();
    expect(screen.queryByText(/Run errored/)).not.toBeInTheDocument();
    expect(screen.queryByText("The Tribune")).not.toBeInTheDocument();
  });

  it("a run's task PARAGRAPH never becomes the row label — first line + run id (audit 2026-08-22)", async () => {
    renderWs();
    expect(await screen.findByText("Build the thing")).toBeInTheDocument();
    expect(screen.queryByText(/must render a headline and a CTA/)).not.toBeInTheDocument();
    // Search still reads the FULL stored task, so nothing became unfindable by shortening it.
    fireEvent.change(screen.getByLabelText("Search events"), {
      target: { value: "headline and a CTA" },
    });
    expect(await screen.findByText("Build the thing")).toBeInTheDocument();
  });
});
