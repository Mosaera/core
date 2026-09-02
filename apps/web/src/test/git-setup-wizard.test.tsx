import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GitHubSetup } from "../components/settings/git/GitHubSetup";
import { GitLabSetup } from "../components/settings/git/GitLabSetup";

const mocks = vi.hoisted(() => ({
  githubSetupManifest: vi.fn(),
  githubSetupManual: vi.fn(),
  saveGitlab: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, ...mocks } };
});

function renderWizard(ui: React.ReactElement) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("GitHub first-run setup", () => {
  // The point of the GitHub path: no credential is typed. If this ever regresses to a form,
  // the setup this slice removed has come back.
  it("offers one button and asks for no credentials", () => {
    renderWizard(<GitHubSetup onDone={() => {}} />);
    expect(screen.getByRole("button", { name: "Create GitHub App" })).toBeInTheDocument();
    expect(screen.queryByText(/Private key/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Client secret/)).not.toBeInTheDocument();
  });

  it("states the two permissions it will ask GitHub for", () => {
    renderWizard(<GitHubSetup onDone={() => {}} />);
    expect(screen.getByText("Contents: read & write")).toBeInTheDocument();
    expect(screen.getByText("Pull requests: read & write")).toBeInTheDocument();
  });

  it("keeps a manual escape hatch for an app that already exists", async () => {
    renderWizard(<GitHubSetup onDone={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "I already have one" }));
    expect(await screen.findByText("Private key (PEM)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
  });

  it("surfaces a failed registration instead of leaving a dead button", async () => {
    mocks.githubSetupManifest.mockRejectedValue(new Error("set this instance's public URL"));
    renderWizard(<GitHubSetup onDone={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Create GitHub App" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("public URL");
  });
});

describe("GitLab first-run setup", () => {
  // The redirect URI is DERIVED from this instance. A hardcoded one is wrong for every
  // self-hosted install, and wrong in a way that only surfaces as an opaque OAuth error later.
  it("shows the redirect URI for THIS instance, not a hardcoded one", () => {
    renderWizard(<GitLabSetup onDone={() => {}} />);
    expect(
      screen.getByText(`${window.location.origin}/oauth/callback`),
    ).toBeInTheDocument();
    expect(screen.getByText("api")).toBeInTheDocument();
  });

  it("will not submit until every required value is present", () => {
    renderWizard(<GitLabSetup onDone={() => {}} />);
    const cta = screen.getByRole("button", { name: "Continue" });
    expect(cta).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("https://gitlab.company.com"), {
      target: { value: "https://gitlab.example.com" },
    });
    fireEvent.change(screen.getByPlaceholderText("Your OAuth application ID"), {
      target: { value: "appid" },
    });
    expect(cta).toBeDisabled(); // secret still missing
    fireEvent.change(screen.getByPlaceholderText("Your OAuth application secret"), {
      target: { value: "s3cret" },
    });
    expect(cta).toBeEnabled();
  });

  it("saves the instance URL, the pair, and this instance's own base URL", async () => {
    mocks.saveGitlab.mockResolvedValue({ configured: true });
    const onDone = vi.fn();
    renderWizard(<GitLabSetup onDone={onDone} />);

    fireEvent.change(screen.getByPlaceholderText("https://gitlab.company.com"), {
      target: { value: "https://gitlab.example.com" },
    });
    fireEvent.change(screen.getByPlaceholderText("Your OAuth application ID"), {
      target: { value: "appid" },
    });
    fireEvent.change(screen.getByPlaceholderText("Your OAuth application secret"), {
      target: { value: "s3cret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(mocks.saveGitlab).toHaveBeenCalled());
    expect(mocks.saveGitlab.mock.calls[0][0]).toEqual({
      url: "https://gitlab.example.com",
      base_url: window.location.origin,
      oauth_client_id: "appid",
      oauth_client_secret: "s3cret",
    });
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });
});
