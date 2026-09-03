import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../api/authContext";
import type { Project } from "../api/client";
import type { DeliveryCapability } from "../api/delivery";
import { GitHubPanel } from "../components/settings/git/GitHubPanel";
import { ownerOf } from "../components/settings/git/ownerOf";
import { ProjectSettingsWorkspace } from "../components/settings/ProjectSettingsWorkspace";

const mocks = vi.hoisted(() => ({
  githubStatus: vi.fn(),
  githubInstallations: vi.fn(),
  listProjects: vi.fn(),
  gitlabOauthStatus: vi.fn(),
  gitlabStatus: vi.fn(),
  projectBudget: vi.fn(),
  projectCost: vi.fn(),
  projectDeliveryCapability: vi.fn(),
  connectGithub: vi.fn(),
  githubRepoStatus: vi.fn(),
  gitlabRepoStatus: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: { ...mod.api, ...mocks },
  };
});

vi.mock("../api/delivery", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/delivery")>();
  return {
    ...mod,
    deliveryApi: {
      ...mod.deliveryApi,
      projectDeliveryCapability: mocks.projectDeliveryCapability,
    },
  };
});

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1",
    name: "Demo",
    source_repo: "https://github.com/acme/widget.git",
    goal: "g",
    brief: "b",
    status: "active",
    branch: "mosaera/x",
    mr_url: "",
    autonomous: false,
    has_gitlab_token: false,
    gitlab_token_masked: "",
    error: "",
    created_at: "2026-07-01T00:00:00Z",
    backlog: [],
    runs: [],
    ...over,
  };
}

function capability(over: Partial<DeliveryCapability> = {}): DeliveryCapability {
  return {
    provider: "github",
    can_finish: true,
    reason: null,
    detail: "",
    has_gitlab_token: false,
    has_gitlab_api_token: false,
    merge_state_readable: true,
    ...over,
  };
}

function renderWith(ui: React.ReactElement, entry = "/") {
  return render(
    <AuthProvider>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryRouter initialEntries={[entry]}>{ui}</MemoryRouter>
      </QueryClientProvider>
    </AuthProvider>,
  );
}

/** The pane lives in `?pane=`, so the tests open Integration directly rather than rendering
 *  General (whose budget/cost cards are a different surface with its own fixtures). */
const INTEGRATION = "/?pane=integration";

const ADMIN = { auth_required: true, user: { id: 1, username: "admin", is_admin: true } };

beforeEach(() => {
  vi.clearAllMocks();
  // AuthProvider probes /api/auth/status directly; the panel's fetch gate reads it.
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(ADMIN), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    ),
  );
  mocks.githubStatus.mockResolvedValue({ configured: true, is_admin: true, install_url: "" });
  mocks.githubInstallations.mockResolvedValue({
    configured: true,
    installations: [],
    install_url: "",
    error: null,
  });
  mocks.listProjects.mockResolvedValue({ projects: [] });
  mocks.gitlabOauthStatus.mockResolvedValue({ configured: false, is_admin: true, host: "gl.test" });
  mocks.gitlabStatus.mockResolvedValue({ configured: false });
  mocks.projectBudget.mockResolvedValue({});
  mocks.projectCost.mockResolvedValue({});
  mocks.githubRepoStatus.mockResolvedValue({ configured: false, is_admin: true, host: "github.com" });
  mocks.gitlabRepoStatus.mockResolvedValue({ configured: false, is_admin: true, host: "gitlab.test" });
});

describe("ownerOf", () => {
  it("reads the account from https and scp GitHub sources", () => {
    expect(ownerOf("https://github.com/acme/widget.git")).toBe("acme");
    expect(ownerOf("git@github.com:acme/widget.git")).toBe("acme");
  });

  // The same host-equality rule TM-0002/M-1 established for the delivery path. A substring
  // test would count these as GitHub, and the two surfaces would then disagree about what a
  // GitHub project even is.
  it("rejects look-alike hosts rather than matching on a substring", () => {
    for (const src of [
      "https://github.com.evil.io/acme/widget.git",
      "https://evil.io/github.com/acme/widget.git",
      "https://gitlab.example.com/acme/widget.git",
    ]) {
      expect(ownerOf(src)).toBeNull();
    }
  });
});

describe("GitHubPanel", () => {
  // The state right after registration: the app exists but reaches nothing. It used to be
  // headed "Select installation" over an empty list reading "No installations available" — a
  // choice the operator cannot make, and an absence reported as though something were wrong.
  it("frames an app that is registered but installed nowhere as the next step", async () => {
    mocks.githubInstallations.mockResolvedValue({
      configured: true,
      installations: [],
      install_url: "https://github.com/apps/mosaera/installations/new",
      error: null,
    });
    renderWith(<GitHubPanel />);

    // The setup checklist marks step 1 done and step 2 as the live one, rather than reporting
    // the ordinary just-registered state as an absence.
    expect(await screen.findByText("Install it on an account")).toBeInTheDocument();
    expect(screen.queryByText("No installations available")).not.toBeInTheDocument();
    expect(screen.queryByText("Select installation")).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Install on GitHub" })).toBeInTheDocument();
    expect(screen.getByText(/cannot see any repositories until it is installed/)).toBeInTheDocument();
  });

  it("does not ask the operator to select from a list nothing selects from", async () => {
    mocks.githubInstallations.mockResolvedValue({
      configured: true,
      installations: [
        { id: 1, account: "acme", account_type: "User", avatar_url: null, repository_selection: "all" },
      ],
      install_url: "https://github.com/apps/mosaera/installations/new",
      error: null,
    });
    renderWith(<GitHubPanel />);

    // Nothing is selected here — the rows state what the app can reach, and delivery picks the
    // installation from the project's own repository.
    expect(await screen.findByText(/nothing to choose here/)).toBeInTheDocument();
    expect(screen.queryByText("Select installation")).not.toBeInTheDocument();
    // "another account" is only true once there IS one.
    expect(await screen.findByRole("link", { name: "Install on another account" })).toBeInTheDocument();
  });

  it("lists the projects that point at GitHub, with their owning account", async () => {
    mocks.githubInstallations.mockResolvedValue({
      configured: true,
      installations: [
        { id: 1, account: "acme", account_type: "Organization", avatar_url: null, repository_selection: "all" },
      ],
      install_url: "",
      error: null,
    });
    mocks.listProjects.mockResolvedValue({
      projects: [project(), project({ id: "p2", source_repo: "https://github.com/other/x.git" })],
    });
    renderWith(<GitHubPanel />);

    const rows = (await screen.findByRole("table")).querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("acme/widget");
    expect(rows[0].textContent).toContain("acme");
    expect(rows[1].textContent).toContain("other/x");
  });
});

describe("the project Integration pane", () => {
  // #120's remaining untruth: this pane rendered the GitLab card for every project, so a
  // GitHub-backed one was told to paste a GitLab token it can never use.
  it("shows GitHub, and no GitLab token prose, for a GitHub project", async () => {
    mocks.projectDeliveryCapability.mockResolvedValue(capability());
    renderWith(<ProjectSettingsWorkspace project={project()} />, INTEGRATION);

    expect(await screen.findByRole("heading", { name: "GitHub" })).toBeInTheDocument();
    expect(screen.queryByText(/write_repository/)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "GitLab" })).not.toBeInTheDocument();
  });

  // F8/F9/F10: defaulting to "gitlab" while the capability query was in flight flashed the
  // GitLab card for every project, local ones included, for the request's duration.
  it("renders no forge card while the capability query is still in flight", async () => {
    let resolve!: (v: DeliveryCapability) => void;
    mocks.projectDeliveryCapability.mockReturnValue(
      new Promise<DeliveryCapability>((r) => {
        resolve = r;
      }),
    );
    renderWith(
      <ProjectSettingsWorkspace project={project({ source_repo: "/home/me/ledgercli" })} />,
      INTEGRATION,
    );

    // Give the microtask queue a turn without ever resolving the capability fetch.
    await Promise.resolve();
    expect(screen.queryByRole("heading", { name: "GitLab" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "GitHub" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Repository" })).not.toBeInTheDocument();

    resolve(capability({ provider: "gitlab", has_gitlab_token: true }));
    expect(await screen.findByRole("heading", { name: "GitLab" })).toBeInTheDocument();
  });

  it("still shows GitLab for a GitLab project", async () => {
    mocks.projectDeliveryCapability.mockResolvedValue(
      capability({ provider: "gitlab", has_gitlab_token: true }),
    );
    renderWith(
      <ProjectSettingsWorkspace
        project={project({ source_repo: "https://gitlab.rengifo.me/m/d.git" })}
      />,
      INTEGRATION,
    );

    expect(await screen.findByRole("heading", { name: "GitLab" })).toBeInTheDocument();
  });

  // Re-homed from delivery-capability.test.tsx when Connect moved here: the payload assertion
  // is ADR-0114's whole security argument and must live wherever the button lives.
  it("connects by posting a project id and nothing from any redirect", async () => {
    mocks.projectDeliveryCapability.mockResolvedValue(capability({ has_github_connection: false }));
    mocks.connectGithub.mockResolvedValue({ connected: true, owner_repo: "acme/widget" });
    renderWith(<ProjectSettingsWorkspace project={project()} />, INTEGRATION);

    fireEvent.click(await screen.findByRole("button", { name: "Connect GitHub" }));
    await waitFor(() => expect(mocks.connectGithub).toHaveBeenCalled());
    // No installation_id, no code, no state — there is nothing for anyone to forge.
    expect(mocks.connectGithub.mock.calls[0]).toEqual(["p1"]);
  });

  // ADR-0120/0125. A project with code on disk is the common case: it is not on a forge, so it
  // can have a repository created and its history pushed into it — by EITHER provider.
  it("offers every forge that can actually publish it", async () => {
    mocks.githubRepoStatus.mockResolvedValue({
      configured: true,
      is_admin: true,
      host: "github.com",
    });
    mocks.gitlabRepoStatus.mockResolvedValue({
      configured: true,
      is_admin: true,
      host: "gitlab.test",
    });
    mocks.projectDeliveryCapability.mockResolvedValue(capability({ provider: "unknown" }));
    renderWith(
      <ProjectSettingsWorkspace project={project({ source_repo: "/home/me/ledgercli" })} />,
      INTEGRATION,
    );

    const ctas = await screen.findAllByRole("button", { name: "Create and push" });
    expect(ctas.map((c) => c.getAttribute("href"))).toEqual([
      "/api/oauth/github/start?project_id=p1",
      "/api/oauth/gitlab/create/start?project_id=p1",
    ]);
    // The visibility difference is real and is stated per provider rather than smoothed over.
    expect(screen.getByText(/Created public/)).toBeInTheDocument();
    expect(screen.getByText(/Created private/)).toBeInTheDocument();
  });

  it("withholds a provider this instance cannot actually use", async () => {
    mocks.githubRepoStatus.mockResolvedValue({
      configured: false,
      is_admin: true,
      host: "github.com",
    });
    mocks.gitlabRepoStatus.mockResolvedValue({
      configured: true,
      is_admin: true,
      host: "gitlab.test",
    });
    mocks.projectDeliveryCapability.mockResolvedValue(capability({ provider: "unknown" }));
    renderWith(
      <ProjectSettingsWorkspace project={project({ source_repo: "/home/me/ledgercli" })} />,
      INTEGRATION,
    );

    // Offering a button that fails at the far end of a redirect is not honesty about config.
    const ctas = await screen.findAllByRole("button", { name: "Create and push" });
    expect(ctas).toHaveLength(1);
    expect(ctas[0]).toHaveAttribute("href", "/api/oauth/gitlab/create/start?project_id=p1");
  });

  it("does not dead-end a project when no forge can publish it", async () => {
    mocks.projectDeliveryCapability.mockResolvedValue(capability({ provider: "unknown" }));
    renderWith(
      <ProjectSettingsWorkspace project={project({ source_repo: "/local/path" })} />,
      INTEGRATION,
    );

    expect(await screen.findByRole("heading", { name: "Repository" })).toBeInTheDocument();
    expect(await screen.findByText(/only publishing is unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set one up" })).toBeInTheDocument();
  });

  // Re-homed from delivery-capability.test.tsx when Connect moved here: the payload assertion
  // is ADR-0114's whole security argument and must live wherever the button lives.
  it("connects by posting a project id and nothing from any redirect", async () => {
    mocks.projectDeliveryCapability.mockResolvedValue(capability({ has_github_connection: false }));
    mocks.connectGithub.mockResolvedValue({ connected: true, owner_repo: "acme/widget" });
    renderWith(<ProjectSettingsWorkspace project={project()} />, INTEGRATION);

    fireEvent.click(await screen.findByRole("button", { name: "Connect GitHub" }));
    await waitFor(() => expect(mocks.connectGithub).toHaveBeenCalled());
    // No installation_id, no code, no state — there is nothing for anyone to forge.
    expect(mocks.connectGithub.mock.calls[0]).toEqual(["p1"]);
  });

  // ADR-0120 A1. A project with code on disk is the common case and the one that needs this:
  // it is not on a forge, so it can have a repository created AND its history pushed into it.


  // It used to render a dead end here — "not a recognized forge, nothing you do will change
  // that". That was true only while nothing could be done about it.
});
