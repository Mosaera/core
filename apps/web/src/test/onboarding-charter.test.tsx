import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../api/authContext";
import type { CharterProposal, ProjectMap } from "../api/client";
import { CharterProposalCard } from "../components/pm/CharterProposalCard";
import { ProjectMapCard } from "../components/overview/ProjectMapCard";

const mocks = vi.hoisted(() => ({
  putCharter: vi.fn(),
  getProjectMap: vi.fn(),
  triggerRecon: vi.fn(),
}));
vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      putCharter: mocks.putCharter,
      getProjectMap: mocks.getProjectMap,
      triggerRecon: mocks.triggerRecon,
    },
  };
});

/** `admin` drives useAuth().isAdmin, which now decides whether the confirm writes posture. */
function stubAuth(admin: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      String(url).includes("/api/auth/status")
        ? new Response(
            JSON.stringify({
              auth_required: true,
              user: { id: 1, username: admin ? "admin" : "member", is_admin: admin },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          )
        : new Response("{}", { status: 200 }),
    ),
  );
}

function wrap(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AuthProvider>
        <MemoryRouter>{node}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  stubAuth(true);
  mocks.putCharter.mockReset();
  mocks.getProjectMap.mockReset();
  mocks.triggerRecon.mockReset();
});

describe("CharterProposalCard", () => {
  const proposal: CharterProposal = {
    goal: "ship the MVP",
    constraints: "stdlib only",
    posture: "free",
  };

  it("renders the PARSED posture and its meaning prominently (red-team requirement)", () => {
    wrap(<CharterProposalCard projectId="p1" proposal={proposal} onDecline={() => {}} />);
    // The posture word AND its spelled-out control are both shown — the operator confirms
    // the control, not a bare tier or the chat prose.
    expect(screen.getByText("free")).toBeInTheDocument();
    expect(screen.getByText(/acts autonomously and you review afterward/i)).toBeInTheDocument();
    expect(screen.getByText("ship the MVP")).toBeInTheDocument();
  });

  it("an ADMIN confirm writes the EXACT parsed proposal, posture included (display == write)", async () => {
    mocks.putCharter.mockResolvedValue({ ...proposal, project_id: "p1" });
    wrap(<CharterProposalCard projectId="p1" proposal={proposal} onDecline={() => {}} />);
    // AuthProvider resolves is_admin asynchronously; until it does the card renders its
    // member form. Clicking before that would test the wrong branch.
    await waitFor(() =>
      expect(screen.queryByText(/only an administrator can change/i)).not.toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /confirm.*save charter/i }));
    await waitFor(() => expect(mocks.putCharter).toHaveBeenCalledWith("p1", proposal));
    expect(await screen.findByText(/charter saved/i)).toBeInTheDocument();
  });

  it("a MEMBER confirm records intent and omits posture — and says so", async () => {
    // The 403 dead-end this replaces was the product's primary journey. Omitting posture is what
    // the server reads as "leave governance alone"; sending it would 403 for a member.
    stubAuth(false);
    mocks.putCharter.mockResolvedValue({ ...proposal, project_id: "p1" });
    wrap(<CharterProposalCard projectId="p1" proposal={proposal} onDecline={() => {}} />);
    // The posture is still shown in full — the red-team requirement is unchanged.
    expect(await screen.findByText("free")).toBeInTheDocument();
    expect(screen.getByText(/only an administrator can change/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /confirm.*save charter/i }));
    await waitFor(() =>
      expect(mocks.putCharter).toHaveBeenCalledWith("p1", {
        goal: "ship the MVP",
        constraints: "stdlib only",
      }),
    );
  });

  it("declining never writes; it sends feedback to Quincy", () => {
    const onDecline = vi.fn();
    wrap(<CharterProposalCard projectId="p1" proposal={proposal} onDecline={onDecline} />);
    fireEvent.click(screen.getByRole("button", { name: /not yet/i }));
    expect(onDecline).toHaveBeenCalled();
    expect(mocks.putCharter).not.toHaveBeenCalled();
  });
});

describe("ProjectMapCard", () => {
  function map(over: Partial<ProjectMap> = {}): ProjectMap {
    return {
      dimensions: [
        {
          dimension: "tests",
          status: "unavailable",
          unavailable_reason: "no test files found",
          computed_at: "2026-07-22T10:00:00Z",
          observations: [],
        },
        {
          dimension: "security",
          status: "finding",
          computed_at: "2026-07-22T10:00:00Z",
          observations: [{ provenance: "app.py:12", text: "eval() on user input" }],
        },
      ],
      stale: ["docs"],
      running: false,
      ...over,
    };
  }

  it("renders tri-state, the honest unavailable reason, and provenance", async () => {
    mocks.getProjectMap.mockResolvedValue(map());
    wrap(<ProjectMapCard projectId="p1" />);
    expect(await screen.findByText("tests")).toBeInTheDocument();
    expect(screen.getByText("unavailable")).toBeInTheDocument();
    expect(screen.getByText("no test files found")).toBeInTheDocument();
    expect(screen.getByText(/eval\(\) on user input/)).toBeInTheDocument();
    expect(screen.getByText("app.py:12")).toBeInTheDocument();
  });

  it("re-run recon triggers a recon sweep", async () => {
    mocks.getProjectMap.mockResolvedValue(map());
    mocks.triggerRecon.mockResolvedValue({ status: "reconning" });
    wrap(<ProjectMapCard projectId="p1" />);
    fireEvent.click(await screen.findByRole("button", { name: /re-run recon/i }));
    await waitFor(() => expect(mocks.triggerRecon).toHaveBeenCalledWith("p1"));
  });

  it("colours a finding by its worst observation: inventory stays neutral, a concern elevates", async () => {
    mocks.getProjectMap.mockResolvedValue({
      dimensions: [
        {
          dimension: "structure", // pure inventory → all info → neutral badge, no dots
          status: "finding",
          computed_at: "t",
          observations: [
            { provenance: "tool:walk", text: "23 files", severity: "info" },
            { provenance: "tool:walk", text: "file types: .py (16)", severity: "info" },
          ],
        },
        {
          dimension: "quality", // a real concern → elevated badge + a severity dot
          status: "finding",
          computed_at: "t",
          observations: [{ provenance: "tool:mypy", text: "2 type errors", severity: "high" }],
        },
      ],
      stale: [],
      running: false,
    });
    wrap(<ProjectMapCard projectId="p1" />);
    await screen.findByText("structure");

    // The all-info "structure" finding is neutral (secondary), NOT the amber default — the
    // screenshot bug fixed. The elevated "quality" finding is destructive.
    const badges = screen.getAllByText("finding");
    const structureBadge = badges[0];
    const qualityBadge = badges[1];
    expect(structureBadge.className).toContain("secondary");
    expect(qualityBadge.className).toContain("destructive");

    // The high observation gets a severity dot; the info observations get none.
    expect(screen.getByLabelText("high severity")).toBeInTheDocument();
    expect(screen.queryByLabelText("info severity")).not.toBeInTheDocument();
  });
});
