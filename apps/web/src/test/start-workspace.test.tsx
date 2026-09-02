import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project, ProjectMessage } from "../api/client";
import { StartWorkspace } from "../components/start/StartWorkspace";

const mocks = vi.hoisted(() => ({
  projectMessages: vi.fn(),
  approveProject: vi.fn(),
  retryIntake: vi.fn(),
}));
vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      projectMessages: mocks.projectMessages,
      approveProject: mocks.approveProject,
      retryIntake: mocks.retryIntake,
    },
  };
});
// The chat panel is exercised elsewhere; this test is about the Build gating.
// The setup checklist has its own suite (setup-panel.test.tsx); this file is about Build gating.
vi.mock("../components/start/SetupPanel", () => ({ SetupPanel: () => null }));
vi.mock("../components/pm/PmChatPanel", () => ({ PmChatPanel: () => <div>chat</div> }));

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1",
    name: "P",
    source_repo: "r",
    status: "ready",
    backlog: [],
    runs: [],
    created_at: null,
    ...over,
  } as Project;
}

function renderWs(p: Project, messages: ProjectMessage[] = []) {
  mocks.projectMessages.mockResolvedValue({ messages });
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <StartWorkspace project={p} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.projectMessages.mockResolvedValue({ messages: [] });
  mocks.approveProject.mockResolvedValue(project({ status: "active" }));
  mocks.retryIntake.mockResolvedValue(project({ status: "drafting", error: "" }));
});

describe("StartWorkspace", () => {
  it("disables Build while the repo is still cloning", async () => {
    renderWs(project({ status: "drafting" }));
    expect(await screen.findByText(/setting up the repository/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Build the backlog/ })).toBeDisabled();
  });

  it("disables Build until the stakeholder has said something", async () => {
    renderWs(project({ status: "ready" }), []);
    expect(await screen.findByText(/Describe your goal/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Build the backlog/ })).toBeDisabled();
  });

  it("enables Build once there's a message, and kicks off decomposition", async () => {
    renderWs(project({ status: "ready" }), [
      { id: 1, role: "user", content: "add a footer", created_at: null } as ProjectMessage,
    ]);
    const btn = await screen.findByRole("button", { name: /Build the backlog/ });
    await waitFor(() => expect(btn).toBeEnabled());
    fireEvent.click(btn);
    await waitFor(() => expect(mocks.approveProject).toHaveBeenCalledWith("p1"));
  });
});

// A failed intake and a starting one are BOTH status "draft". Reading only the status is what made
// a typo'd repo URL render "Quincy is setting up the repository…" forever, with the server's reason
// held in `project.error` and displayed nowhere, and no way to re-run the clone.
describe("a failed intake", () => {
  const dead = () =>
    project({ status: "draft", error: "intake failed: repository 'x' does not exist" });

  it("shows the server's own reason instead of an endless 'setting up'", async () => {
    renderWs(dead());
    expect(await screen.findByText(/repository 'x' does not exist/)).toBeInTheDocument();
    expect(screen.queryByText(/setting up the repository/i)).toBeNull();
  });

  it("offers a retry that re-runs the clone in place", async () => {
    renderWs(dead());
    fireEvent.click(await screen.findByRole("button", { name: /Try again/i }));
    await waitFor(() => expect(mocks.retryIntake).toHaveBeenCalledWith("p1"));
  });

  it("names the fix when the failure looks like authentication", async () => {
    renderWs(project({ status: "draft", error: "intake failed: HTTP 403 authentication failed" }));
    expect(await screen.findByText(/Settings → Integration/)).toBeInTheDocument();
  });

  it("does not offer a retry to a project that is merely starting", async () => {
    renderWs(project({ status: "drafting", error: "" }));
    expect(await screen.findByText(/setting up the repository/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Try again/i })).toBeNull();
  });
});
