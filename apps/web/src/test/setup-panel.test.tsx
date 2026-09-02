import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../api/authContext";
import type { ProjectSetup } from "../api/client";
import { SetupPanel } from "../components/start/SetupPanel";

const mocks = vi.hoisted(() => ({ projectSetup: vi.fn(), saveProjectSetup: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      projectSetup: mocks.projectSetup,
      saveProjectSetup: mocks.saveProjectSetup,
    },
  };
});

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

/** A greenfield project with nothing configured — the newcomer's actual starting state, and the
 *  one whose default terminal outcome is a park. */
function greenfield(over: Partial<ProjectSetup> = {}): ProjectSetup {
  return {
    completed_at: null,
    current: {
      run_mode: "guided",
      posture: "business",
      test_cmd: "",
      tester_enabled: false,
      budget_usd: null,
      budget_tokens: null,
    },
    choices: {
      run_mode: ["autonomous", "guided", "high_assurance"],
      posture: ["business", "free", "regulated"],
      cost_mode: ["economy", "balanced", "premium"],
    },
    tester_knob: { value: false, source: "default", clamped_by: null },
    available: true,
    shapes: ["empty", "greenfield", "sources_no_suite", "standing_suite"],
    repo_shape: {
      shape: "greenfield",
      source_files: 4,
      test_files: 0,
      plan_strength: "shallow",
      plan_reason: "no test suite found; checking that the code parses",
      project_type: "python-scripts",
      truncated: false,
      needs_an_oracle: true,
      evidence: ["4 source file(s) and 0 test file(s) (tool:walk)"],
    },
    oracle_plan: {
      legs: {
        tester_vouched: false,
        standing_suite: false,
        test_cmd: false,
        structural_vouch: false,
      },
      verified_possible: false,
      recommended_knobs: ["tester_enabled"],
      recommend_test_cmd: true,
    },
    ...over,
  };
}

function wrap() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AuthProvider>
        <MemoryRouter>
          <SetupPanel projectId="p1" />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  stubAuth(true);
  mocks.projectSetup.mockReset();
  mocks.saveProjectSetup.mockReset();
});

describe("the setup card is a checklist, not a wizard", () => {
  it("arrives pre-filled: the accept button works with zero prior interaction", async () => {
    // The property the activation evidence turns on. A form of blank fields is where people stop,
    // so the card must PROPOSE — and its proposal must be savable in one click.
    mocks.projectSetup.mockResolvedValue(greenfield());
    mocks.saveProjectSetup.mockResolvedValue(greenfield({ completed_at: "t" }));
    wrap();

    const accept = await screen.findByRole("button", { name: /looks right/i });
    fireEvent.click(accept);
    await waitFor(() => expect(mocks.saveProjectSetup).toHaveBeenCalled());
    // The recommendation was applied, not merely displayed.
    expect(mocks.saveProjectSetup.mock.calls[0][1]).toMatchObject({
      tester_enabled: true,
      completed: true,
    });
  });

  it("says 'keep these settings' when it is not proposing a change", async () => {
    // Honesty in the button: "Looks right" on a card that changes nothing would imply a fix it is
    // not making. A repo with a standing suite needs no recommendation.
    mocks.projectSetup.mockResolvedValue(
      greenfield({
        repo_shape: { ...greenfield().repo_shape!, shape: "standing_suite", needs_an_oracle: false },
        oracle_plan: {
          legs: {
            tester_vouched: false,
            standing_suite: true,
            test_cmd: false,
            structural_vouch: false,
          },
          verified_possible: true,
          recommended_knobs: [],
          recommend_test_cmd: false,
        },
      }),
    );
    wrap();
    expect(await screen.findByRole("button", { name: /keep these settings/i })).toBeTruthy();
  });

  it("opens on the one row that decides whether a run can conclude", async () => {
    mocks.projectSetup.mockResolvedValue(greenfield());
    wrap();
    // The oracle row is expanded; the other two are collapsed but still readable from their
    // summaries — a checklist you must expand to read is a wizard.
    await screen.findByRole("switch", { name: /proctor writes the acceptance test/i });
    expect(screen.queryByLabelText("Run mode")).toBeNull();
    expect(screen.getByRole("button", { name: /how much it asks you/i })).toBeTruthy();
  });
});

describe("it states what was measured, and what that means", () => {
  it("names the repo shape and the honest expectation", async () => {
    mocks.projectSetup.mockResolvedValue(greenfield());
    wrap();
    expect(await screen.findByText(/has code but no tests/i)).toBeTruthy();
    // The measured rate, up front — miscalibrated expectations are the trust failure this avoids.
    expect(screen.getByText(/measured worst/i)).toBeTruthy();
  });

  it("explains the park mechanic in operator language, on demand", async () => {
    mocks.projectSetup.mockResolvedValue(greenfield());
    wrap();
    fireEvent.click(await screen.findByRole("button", { name: /what this means/i }));
    // No jargon: the operator is told the code's own tests do not count and why.
    expect(screen.getByText(/prove only that it agrees with itself/i)).toBeTruthy();
    // And the claim is backed by the provenanced evidence the server produced.
    expect(screen.getByText(/tool:walk/)).toBeTruthy();
  });

  it("warns when nothing could vouch, and stops warning once something can", async () => {
    mocks.projectSetup.mockResolvedValue(
      greenfield({ tester_knob: { value: false, source: "env", clamped_by: null } }),
    );
    wrap();
    // env-pinned: the toggle is not editable here, so the card starts unable to verify.
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/nothing independent can vouch/i);

    fireEvent.change(screen.getByLabelText("Test command"), { target: { value: "pytest -q" } });
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("does not render a shape while the clone is still being fetched", async () => {
    mocks.projectSetup.mockResolvedValue(
      greenfield({
        available: false,
        reason: "the repository clone is not readable yet",
        repo_shape: undefined,
        oracle_plan: undefined,
      }),
    );
    wrap();
    expect(await screen.findByText(/not readable yet/i)).toBeTruthy();
    expect(screen.queryByText(/measured worst/i)).toBeNull(); // never a guess
  });
});

describe("enumerables are dropdowns rendered from the server's own sets", () => {
  it("run mode and posture are selects over the served choices", async () => {
    mocks.projectSetup.mockResolvedValue(greenfield());
    wrap();
    fireEvent.click(await screen.findByRole("button", { name: /how much it asks you/i }));
    const mode = screen.getByLabelText("Run mode");
    expect(mode.tagName.toLowerCase()).not.toBe("input"); // never free text (ADR-0005)

    fireEvent.click(screen.getByRole("button", { name: /what this deployment permits/i }));
    expect(screen.getByLabelText("Governance posture")).toBeTruthy();
  });
});

describe("authority is respected in the body it sends", () => {
  it("a member's save omits posture and the deployment-global knob", async () => {
    stubAuth(false);
    mocks.projectSetup.mockResolvedValue(greenfield());
    mocks.saveProjectSetup.mockResolvedValue(greenfield({ completed_at: "t" }));
    wrap();
    fireEvent.click(await screen.findByRole("button", { name: /looks right|keep these/i }));
    await waitFor(() => expect(mocks.saveProjectSetup).toHaveBeenCalled());
    const body = mocks.saveProjectSetup.mock.calls[0][1];
    // Omitted reads as "leave alone" server-side, so a member can never move governance by saving
    // their own project's settings.
    expect(body).not.toHaveProperty("posture");
    expect(body).not.toHaveProperty("tester_enabled");
  });
});

describe("an answered card collapses instead of nagging", () => {
  it("shows a one-line summary once setup has been answered", async () => {
    mocks.projectSetup.mockResolvedValue(greenfield({ completed_at: "2026-08-24T00:00:00Z" }));
    wrap();
    expect(await screen.findByText(/setup answered/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /looks right/i })).toBeNull();
  });
});
