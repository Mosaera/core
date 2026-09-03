import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GitlabStatus, Project } from "../api/client";
import { GitLabConnection } from "../components/settings/gitlab/GitLabConnection";

const mocks = vi.hoisted(() => ({
  gitlabOauthStatus: vi.fn(),
  gitlabStatus: vi.fn(),
  saveGitlab: vi.fn(),
  setProjectToken: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      gitlabOauthStatus: mocks.gitlabOauthStatus,
      gitlabStatus: mocks.gitlabStatus,
      saveGitlab: mocks.saveGitlab,
      setProjectToken: mocks.setProjectToken,
    },
  };
});

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", name: "Demo", source_repo: "https://gitlab.rengifo.me/m/d.git", goal: "g", brief: "b",
    status: "active", branch: "mosaera/x", mr_url: "", autonomous: false,
    has_gitlab_token: false, gitlab_token_masked: "", error: "",
    created_at: "2026-07-01T00:00:00Z", backlog: [], runs: [], ...over,
  };
}

function glStatus(over: Partial<GitlabStatus> = {}): GitlabStatus {
  return { configured: true, url: "https://gitlab.rengifo.me", ...over };
}

function renderConnection(p: Project = project()) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <GitLabConnection project={p} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.gitlabOauthStatus.mockResolvedValue({
    configured: true,
    is_admin: true,
    host: "gitlab.rengifo.me",
  });
  mocks.gitlabStatus.mockResolvedValue(glStatus({ oauth_configured: true }));
  mocks.saveGitlab.mockResolvedValue(glStatus({ oauth_configured: true }));
  mocks.setProjectToken.mockResolvedValue(project({ has_gitlab_token: true }));
});

describe("GitLab connection — the one control", () => {
  it("admin, app registered, project unlinked: the button says Connect", async () => {
    renderConnection();
    expect(await screen.findByRole("button", { name: "Connect GitLab" })).toBeInTheDocument();
    expect(screen.getByText(/authorize on gitlab.rengifo.me/)).toBeInTheDocument();
  });

  it("admin, no OAuth app yet: the button says Configure and opens on the setup step", async () => {
    mocks.gitlabOauthStatus.mockResolvedValue({
      configured: false,
      is_admin: true,
      host: "gitlab.rengifo.me",
    });
    mocks.gitlabStatus.mockResolvedValue(glStatus({ oauth_configured: false }));
    renderConnection();
    fireEvent.click(await screen.findByRole("button", { name: "Configure GitLab" }));
    // The modal carries the instructions and the two values — not a link to go read docs elsewhere.
    expect(await screen.findByText("Set up GitLab")).toBeInTheDocument();
    expect(screen.getByLabelText("OAuth application id")).toBeInTheDocument();
    expect(screen.getByLabelText("OAuth application secret")).toBeInTheDocument();
    expect(screen.getByText(/oauth\/callback/)).toBeInTheDocument();
  });

  it("saving the app advances to Connect without leaving the modal", async () => {
    mocks.gitlabOauthStatus.mockResolvedValue({
      configured: false,
      is_admin: true,
      host: "gitlab.rengifo.me",
    });
    mocks.gitlabStatus.mockResolvedValue(glStatus({ oauth_configured: false }));
    renderConnection();
    fireEvent.click(await screen.findByRole("button", { name: "Configure GitLab" }));
    fireEvent.change(await screen.findByLabelText("OAuth application id"), {
      target: { value: "app-id" },
    });
    fireEvent.change(screen.getByLabelText("OAuth application secret"), {
      target: { value: "s3cret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));
    await waitFor(() =>
      expect(mocks.saveGitlab).toHaveBeenCalledWith(
        expect.objectContaining({ oauth_client_id: "app-id", oauth_client_secret: "s3cret" }),
      ),
    );
    expect(await screen.findByRole("button", { name: "Authorize with GitLab" })).toBeInTheDocument();
  });

  it("env-pinned config is read-only, and says why", async () => {
    mocks.gitlabStatus.mockResolvedValue(
      glStatus({ oauth_configured: true, oauth_env_pinned: true }),
    );
    renderConnection();
    fireEvent.click(await screen.findByRole("button", { name: "Connect GitLab" }));
    fireEvent.click(await screen.findByRole("button", { name: "Change the OAuth application" }));
    expect(await screen.findByLabelText("OAuth application id")).toBeDisabled();
    expect(screen.getByText(/pinned by/)).toBeInTheDocument();
  });

  it("Disconnect confirms first, and says the secret is unrecoverable", async () => {
    renderConnection();
    fireEvent.click(await screen.findByRole("button", { name: "Connect GitLab" }));
    fireEvent.click(await screen.findByRole("button", { name: "Change the OAuth application" }));
    fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    // Nothing cleared yet — this wipes an INSTANCE-WIDE credential whose secret can't be re-shown.
    expect(mocks.saveGitlab).not.toHaveBeenCalled();
    const confirm = await screen.findByLabelText("Disconnect the OAuth application?");
    // The consequence is stated IN the confirm: instance-wide, and the secret can't be put back.
    expect(within(confirm).getByText(/whole instance/)).toBeInTheDocument();
    expect(within(confirm).getByText(/generating a new secret/)).toBeInTheDocument();
    fireEvent.click(within(confirm).getByRole("button", { name: "Disconnect" }));
    await waitFor(() =>
      expect(mocks.saveGitlab).toHaveBeenCalledWith({
        base_url: "",
        oauth_client_id: "",
        oauth_client_secret: "",
      }),
    );
  });

  it("cancelling the Disconnect confirm clears nothing", async () => {
    renderConnection();
    fireEvent.click(await screen.findByRole("button", { name: "Connect GitLab" }));
    fireEvent.click(await screen.findByRole("button", { name: "Change the OAuth application" }));
    fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByText("Disconnect the OAuth application?")).not.toBeInTheDocument(),
    );
    expect(mocks.saveGitlab).not.toHaveBeenCalled();
  });

  it("a member sees status only — no Connect button, no token fields", async () => {
    mocks.gitlabOauthStatus.mockResolvedValue({
      configured: true,
      is_admin: false,
      host: "gitlab.rengifo.me",
    });
    renderConnection();
    expect(
      await screen.findByText("Contact your administrator to set up GitLab for this project."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Connect|Configure|Manage/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("New GitLab push token")).not.toBeInTheDocument();
    // A member never even fetches the admin-only config read.
    expect(mocks.gitlabStatus).not.toHaveBeenCalled();
  });

  it("a member on a CONNECTED project still gets no button", async () => {
    mocks.gitlabOauthStatus.mockResolvedValue({
      configured: true,
      is_admin: false,
      host: "gitlab.rengifo.me",
    });
    renderConnection(project({ has_gitlab_token: true, gitlab_token_masked: "glpat-****abcd" }));
    expect(await screen.findByText("Connected to gitlab.rengifo.me")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Connect|Configure|Manage/ })).not.toBeInTheDocument();
  });

  it("connected: the state line names the token and whether the api scope is there", async () => {
    renderConnection(project({ has_gitlab_token: true, gitlab_token_masked: "glpat-****abcd" }));
    expect(await screen.findByRole("button", { name: "Manage" })).toBeInTheDocument();
    expect(screen.getByText(/token glpat-\*\*\*\*abcd · api scope ✗/)).toBeInTheDocument();
  });
});

describe("GitLab connection — the manual token fallback", () => {
  async function openManual() {
    renderConnection(project({ has_gitlab_token: true, gitlab_token_masked: "glpat-****abcd" }));
    fireEvent.click(await screen.findByRole("button", { name: "Manage" }));
    fireEvent.click(await screen.findByText("Enter a token manually instead"));
  }

  it("updates the push token, leaving the api token unchanged", async () => {
    await openManual();
    fireEvent.change(await screen.findByLabelText("New GitLab push token"), {
      target: { value: "glpat-new-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update tokens" }));
    // Only the push token was touched → api token stays undefined (unchanged), never wiped (ADR-0103).
    await waitFor(() =>
      expect(mocks.setProjectToken).toHaveBeenCalledWith("p1", "glpat-new-secret", undefined),
    );
    expect(await screen.findByText("Tokens updated.")).toBeInTheDocument();
  });

  it("can set the api token independently of the push token", async () => {
    await openManual();
    fireEvent.change(await screen.findByLabelText("New GitLab api token"), {
      target: { value: "glpat-api-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update tokens" }));
    await waitFor(() =>
      expect(mocks.setProjectToken).toHaveBeenCalledWith("p1", undefined, "glpat-api-secret"),
    );
  });

  it("token update errors surface inline", async () => {
    mocks.setProjectToken.mockRejectedValue(new Error("400: token can't access the repo"));
    await openManual();
    fireEvent.change(await screen.findByLabelText("New GitLab push token"), {
      target: { value: "bad" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update tokens" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("can't access the repo");
  });
});
