/* Delivery capability on the Delivery page (#120, ADR-0112).
 *
 * The regression: a GitHub-sourced project rendered GitLab token prose and offered an
 * "Open MR" button that could only ever 400. These assert the two halves of the fix —
 * the page says which forge and why it cannot finish, and it stops offering the control
 * that cannot succeed ("a button that 403s is the defect this review keeps finding"). */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../api/authContext";
import type { BacklogItem, Project } from "../api/client";
import { DeliveryWorkspace } from "../components/delivery/DeliveryWorkspace";

const mocks = vi.hoisted(() => ({
  projectDiff: vi.fn(),
  projectMrStatus: vi.fn(),
  listBranches: vi.fn(),
  getGeneralSettings: vi.fn(),
  projectDeliveryCapability: vi.fn(),
  githubStatus: vi.fn(),
  connectGithub: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, ...mocks } };
});

function item(over: Partial<BacklogItem> = {}): BacklogItem {
  return {
    id: 1, project_id: "p1", title: "Hero item", description: "", acceptance: "",
    status: "in_review", position: 0, iteration: null, created_at: null, ...over,
  };
}

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", name: "Demo", source_repo: "https://github.com/owner/repo.git", goal: "g",
    brief: "b", status: "active", branch: "mosaera/x", mr_url: "", autonomous: false,
    has_gitlab_token: false, gitlab_token_masked: "", error: "",
    created_at: "2026-07-01T00:00:00Z", backlog: [item()], runs: [], ...over,
  };
}

function renderDelivery(p: Project) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AuthProvider>
        <MemoryRouter initialEntries={[`/projects/${p.id}/delivery`]}>
          <Routes>
            <Route path="/projects/:id/delivery" element={<DeliveryWorkspace project={p} />} />
            <Route path="/projects/:id/settings" element={<div>settings page</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.projectDiff.mockResolvedValue({
    base: "main", diff: "d", has_changes: true, files: ["a"], remote_synced: true,
  });
  mocks.projectMrStatus.mockResolvedValue({ state: null, url: "", items: [] });
  mocks.listBranches.mockResolvedValue({ branches: [] });
  mocks.getGeneralSettings.mockResolvedValue({ knobs: {} });
  mocks.githubStatus.mockResolvedValue({ configured: true, is_admin: true, install_url: "https://github.com/apps/mosaera/installations/new" });
  mocks.connectGithub.mockResolvedValue({ connected: true, owner_repo: "acme/widget" });
});

describe("delivery capability", () => {
  it("names GitHub and does not offer a control that cannot succeed", async () => {
    mocks.projectDeliveryCapability.mockResolvedValue({
      provider: "github",
      can_finish: false,
      reason: "github_not_connected",
      detail: "This project's source is on GitHub. GitHub delivery is not connected yet.",
      has_gitlab_token: false,
      has_gitlab_api_token: false,
      merge_state_readable: false,
    });
    renderDelivery(project());

    // Stated twice by design: the provider line names the forge, the amber line says what
    // that means for finishing. Both must be present.
    expect((await screen.findAllByText(/source is on GitHub/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/not connected yet/)).toBeInTheDocument();
    // The refusal is stated where the credentials card was, not as an error after a click.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Open MR" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /Open one combined MR/ })).not.toBeInTheDocument();
    // GitLab token prose is not merely unhelpful here — it is untrue, so it is absent.
    expect(screen.queryByText(/write_repository/)).not.toBeInTheDocument();
  });

  it("still offers delivery on a GitLab project that can finish", async () => {
    mocks.projectDeliveryCapability.mockResolvedValue({
      provider: "gitlab",
      can_finish: true,
      reason: null,
      detail: "",
      has_gitlab_token: true,
      has_gitlab_api_token: false,
      merge_state_readable: false,
    });
    renderDelivery(
      project({
        source_repo: "https://gitlab.rengifo.me/m/d.git",
        has_gitlab_token: true,
        gitlab_token_masked: "…ab12",
      }),
    );

    expect(await screen.findByRole("button", { name: "Open MR" })).toBeInTheDocument();
    expect(screen.getByText(/write_repository/)).toBeInTheDocument();
  });

  it("degrades to the GitLab view when the endpoint is unavailable", async () => {
    // An older server has no capability route. The page must keep working exactly as it
    // did rather than blanking or refusing — the fix must not become its own outage.
    mocks.projectDeliveryCapability.mockRejectedValue(new Error("404 Not Found"));
    renderDelivery(
      project({
        source_repo: "https://gitlab.rengifo.me/m/d.git",
        has_gitlab_token: true,
        gitlab_token_masked: "…ab12",
      }),
    );

    expect(await screen.findByRole("button", { name: "Open MR" })).toBeInTheDocument();
    expect(screen.getByText(/write_repository/)).toBeInTheDocument();
  });

  it("says so honestly when the host is not a recognized forge at all", async () => {
    mocks.projectDeliveryCapability.mockResolvedValue({
      provider: "unknown",
      can_finish: false,
      reason: "not_gitlab",
      detail: "Delivery has nowhere to open a request.",
      has_gitlab_token: false,
      has_gitlab_api_token: false,
      merge_state_readable: false,
    });
    renderDelivery(project({ source_repo: "/home/me/local-thing" }));

    expect(await screen.findByText(/not a recognized GitHub repository/)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Open MR" })).not.toBeInTheDocument(),
    );
  });
});


describe("github delivery (ADR-0114)", () => {
  const githubCap = (over: Record<string, unknown> = {}) => ({
    provider: "github",
    can_finish: false,
    reason: "github_not_connected",
    detail: "The Mosaera GitHub App is not installed on this repository yet.",
    note: "GitHub delivery currently covers public repositories.",
    item_requests_supported: false,
    has_gitlab_token: false,
    has_gitlab_api_token: false,
    github_app_configured: true,
    has_github_connection: false,
    merge_state_readable: false,
    ...over,
  });

  // Connect moved to the project's Integration pane so there is ONE connect control rather
  // than one per page — the shape GitLab already had. This card reports state and points at it;
  // the act-and-its-payload assertions now live in `git-settings.test.tsx` against the pane.
  it("states the problem and points at the one place it is fixed", async () => {
    mocks.projectDeliveryCapability.mockResolvedValue(githubCap());
    renderDelivery(project());

    expect(await screen.findByText(/not installed on this repository/)).toBeInTheDocument();
    const cta = await screen.findByRole("button", { name: "Connect GitHub" });
    expect(cta).toHaveAttribute("href", "/projects/p1/settings?pane=integration");
    // This card must no longer carry a connect action of its own.
    expect(mocks.connectGithub).not.toHaveBeenCalled();
    // Not deliverable yet, so the open control is absent rather than present-and-broken.
    expect(screen.queryByRole("button", { name: /Open one combined MR/ })).not.toBeInTheDocument();
  });

  it("a connected project can deliver and says what is not offered", async () => {
    mocks.projectDeliveryCapability.mockResolvedValue(
      githubCap({ can_finish: true, reason: null, detail: "", has_github_connection: true, merge_state_readable: true }),
    );
    renderDelivery(project());

    expect(await screen.findByText(/never stored/)).toBeInTheDocument();
    expect(screen.getByText(/per-item pull requests are GitLab-only/i)).toBeInTheDocument();
    // The per-item control is withheld even though the project CAN deliver.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Open MR" })).not.toBeInTheDocument(),
    );
  });

  it("names the instance-level gap when no App is configured at all", async () => {
    mocks.projectDeliveryCapability.mockResolvedValue(
      githubCap({
        reason: "github_app_unconfigured",
        detail: "this Mosaera instance has no GitHub App configured",
        github_app_configured: false,
      }),
    );
    renderDelivery(project());
    expect(await screen.findByText(/no GitHub App configured/)).toBeInTheDocument();
    // Nothing for a project admin to press here — the remedy is instance configuration.
    expect(screen.queryByRole("button", { name: "Connect" })).not.toBeInTheDocument();
  });
});
