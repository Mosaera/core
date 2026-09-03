import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../api/authContext";
import type { Project } from "../api/client";
import type { Decision } from "../api/delivery";
import { DecisionCard } from "../components/overview/DecisionCard";

const mocks = vi.hoisted(() => ({
  gitlabOauthStatus: vi.fn(),
  gitlabStatus: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      gitlabOauthStatus: mocks.gitlabOauthStatus,
      gitlabStatus: mocks.gitlabStatus,
    },
  };
});

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", name: "Demo", source_repo: "https://gitlab.rengifo.me/m/d.git", goal: "g",
    brief: "b", status: "active", branch: "", mr_url: "", autonomous: false,
    has_gitlab_token: false, gitlab_token_masked: "", error: "",
    created_at: "2026-08-01T00:00:00Z", backlog: [], runs: [], ...over,
  };
}

function decision(over: Partial<Decision> = {}): Decision {
  return {
    id: "integration:configure",
    kind: "integration_missing",
    title: "Connect GitLab to deliver this project",
    summary: "No GitLab application is registered yet.",
    requires_admin: true,
    actions: [{ label: "Set up GitLab", kind: "gitlab_setup" }],
    ...over,
  };
}

function renderCard(d: Decision) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AuthProvider>
        <MemoryRouter>
          <DecisionCard project={project()} decision={d} />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.gitlabStatus.mockResolvedValue({ configured: false, url: "https://gl" });
});

describe("DecisionCard", () => {
  // ADR-0105: the surface must stop offering what the server would 403, rather than the member
  // acquiring an ability. Setting up a credential is a secret write — admin only (ADR-0004).
  it("offers the setup control to an admin", async () => {
    mocks.gitlabOauthStatus.mockResolvedValue({ is_admin: true, configured: false, host: "gl" });
    renderCard(decision());
    expect(await screen.findByRole("button", { name: "Set up GitLab" })).toBeInTheDocument();
  });

  it("shows a member the read-only notice and NO credential control", async () => {
    mocks.gitlabOauthStatus.mockResolvedValue({ is_admin: false, configured: false, host: "gl" });
    renderCard(decision());
    expect(await screen.findByText(/Contact your administrator/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set up GitLab" })).not.toBeInTheDocument();
    // No credential field is reachable from the conversation for a member, under any state.
    expect(screen.queryByLabelText(/secret/i)).not.toBeInTheDocument();
  });

  it("hands a parked run off to the run's own gate rather than deciding anything", async () => {
    mocks.gitlabOauthStatus.mockResolvedValue({ is_admin: true, configured: true, host: "gl" });
    renderCard(
      decision({
        id: "gate:run-7",
        kind: "gate_pending",
        title: "A run is waiting on you",
        summary: "Approve the delivery?",
        requires_admin: false,
        run_id: "run-7",
        actions: [{ label: "Open the gate", kind: "open_run" }],
      }),
    );
    // The shared Button stamps role="button" even when it renders an anchor.
    // 5A-extra: the gate link keeps project context (liveRunHref) instead of dropping to the
    // global /runs/:id route.
    const link = await screen.findByRole("button", { name: /Open the gate/ });
    expect(link).toHaveAttribute("href", "/projects/p1/runs/run-7");
    // Crucially: no approve/deny control here. The gate is the only authority (ADR-0082).
    expect(screen.queryByRole("button", { name: /Approve|Deny/ })).not.toBeInTheDocument();
  });
});

describe("DecisionBand placement on the Overview", () => {
  /* The cards left the PM transcript on 2026-08-22. In the conversation they had no refetch
     interval, no dismissal and no acknowledgment — permanent furniture at the bottom of every
     chat rather than notifications. The live-validation finding this suite originally guarded
     (a brand-new project with zero messages rendered NO card, which is exactly when "connect
     GitLab" matters most) is preserved in a stronger form: the band renders wherever the
     condition is true, independent of any conversation. */
  it("renders a blocking condition on a project with no messages and no runs", async () => {
    mocks.gitlabOauthStatus.mockResolvedValue({ is_admin: true, configured: true, host: "gl" });
    const { DecisionBand } = await import("../components/overview/DecisionBand");
    const { api } = await import("../api/client");
    vi.spyOn(api, "projectDecisions").mockResolvedValue({ decisions: [decision()] });

    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <AuthProvider>
          <MemoryRouter>
            <DecisionBand project={project()} />
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/Connect GitLab to deliver this project/)).toBeInTheDocument();
    // A blocking condition offers NO dismissal: it is cleared by acting, never by hiding
    // (ADR-0107 — an ack keyed to `gate:{run_id}` could silence a later, different question).
    expect(screen.queryByRole("button", { name: /^Dismiss:/ })).not.toBeInTheDocument();
  });

  it("lets a STANDING advisory be dismissed, and it stays dismissed", async () => {
    localStorage.clear();
    const { DecisionBand } = await import("../components/overview/DecisionBand");
    const { api } = await import("../api/client");
    vi.spyOn(api, "projectDecisions").mockResolvedValue({
      decisions: [
        decision({
          id: "delivered-no-mr", kind: "delivered_no_mr", tier: "standing",
          title: "6 delivered items have no merge request",
          summary: "Six items are delivered locally.", actions: [],
        }),
      ],
    });
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <AuthProvider>
          <MemoryRouter>
            <DecisionBand project={project()} />
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>,
    );
    const dismiss = await screen.findByRole("button", { name: /^Dismiss:/ });
    fireEvent.click(dismiss);
    await waitFor(() =>
      expect(screen.queryByText(/6 delivered items have no merge request/)).not.toBeInTheDocument(),
    );
  });
});

describe("DecisionBand error state (5E)", () => {
  // Was the worst of the silently-empty surfaces: a failed fetch rendered nothing, which reads
  // exactly like "nothing needs you" — the one thing this band must never say by accident.
  it("shows a retry instead of silently rendering nothing", async () => {
    const { DecisionBand } = await import("../components/overview/DecisionBand");
    const { api } = await import("../api/client");
    const spy = vi
      .spyOn(api, "projectDecisions")
      .mockRejectedValue(new Error("network unreachable"));

    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <AuthProvider>
          <MemoryRouter>
            <DecisionBand project={project()} />
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/Couldn't check what needs you/)).toBeInTheDocument();
    expect(screen.getByText(/network unreachable/)).toBeInTheDocument();
    const calls = spy.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
    await waitFor(() => expect(spy.mock.calls.length).toBeGreaterThan(calls));
  });
});

describe("delivered-without-MR card", () => {
  it("points at the Delivery page, where the per-item control already lives", async () => {
    mocks.gitlabOauthStatus.mockResolvedValue({ is_admin: false, configured: true, host: "gl" });
    renderCard(
      decision({
        id: "delivered-no-mr",
        kind: "delivered_no_mr",
        title: "6 delivered items have no merge request",
        summary: "#83, #84, #85 — the work is recorded as delivered but nothing proposes it.",
        requires_admin: false,
        actions: [{ label: "Review on the Delivery page", kind: "open_delivery" }],
      }),
    );
    const link = await screen.findByRole("button", { name: /Review on the Delivery page/ });
    expect(link).toHaveAttribute("href", "/projects/p1/delivery");
    // Member-available: opening a merge request needs no admin (ADR-0102).
    expect(screen.queryByText(/Contact your administrator/)).not.toBeInTheDocument();
  });
});

describe("backlog-health card", () => {
  // The card exists so a deterministic check reaches the operator BEFORE a run is spent: on
  // LedgerCLI four consecutive runs ended INCOMPLETE on items these checks already flagged.
  it("sends the operator to the Backlog page, where curate already lives", async () => {
    mocks.gitlabOauthStatus.mockResolvedValue({ is_admin: false, configured: true, host: "gl" });
    renderCard(
      decision({
        id: "backlog-health",
        kind: "backlog_health",
        title: "Some backlog items would waste a run as written",
        summary: "1 group(s) look like the same work: #90, #95. #96 ask for something the delivery agent cannot do.",
        requires_admin: false,
        actions: [{ label: "Review the backlog", kind: "open_backlog" }],
      }),
    );
    const link = await screen.findByRole("button", { name: /Review the backlog/ });
    expect(link).toHaveAttribute("href", "/projects/p1/backlog");
    // Member-available: curating proposes a changeset, which still needs approval to apply.
    expect(screen.queryByText(/Contact your administrator/)).not.toBeInTheDocument();
  });
});
