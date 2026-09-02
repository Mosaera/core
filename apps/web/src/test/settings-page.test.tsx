import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../api/authContext";
import { KnobForm } from "../components/settings/KnobForm";
import { SettingsPage } from "../pages/SettingsPage";

const ADMIN = {
  users_supported: true,
  needs_setup: false,
  auth_required: true,
  user: { id: 1, username: "alex", is_admin: true },
};

function knob(value: unknown, source: string, kind = "int", env = "X", visibility = "developer") {
  return { value, source, kind, env, visibility };
}

// ADR-0122 §6: `developer` knobs live behind a disclosure. Opening it is what a user does to
// reach the mechanics, so the tests below do the same rather than assuming a flat form.
async function revealAdvanced() {
  const toggle = await screen.findByRole("button", { name: /Show advanced configuration/ });
  fireEvent.click(toggle);
}
const CORE_knob = (v: unknown, src: string, kind = "int", env = "X") =>
  knob(v, src, kind, env, "core");
const KNOBS = {
  run_max_usd: CORE_knob(5, "env", "opt_float", "MOSAERA_RUN_MAX_USD"),
  run_max_tokens: knob(null, "default", "opt_int"),
  run_max_tool_calls: knob(null, "default", "opt_int"),
  run_max_seconds: CORE_knob(3600, "default"),
  run_quota_per_day: CORE_knob(0, "default", "int", "MOSAERA_RUN_QUOTA_PER_DAY"),
  run_hard_max_usd: knob(null, "default", "opt_float"),
  run_hard_max_tokens: knob(null, "default", "opt_int"),
  max_iterations: knob(3, "default", "int", "MOSAERA_MAX_ITERATIONS"),
  max_iterations_ceiling: knob(12, "default"),
  stall_detection_enabled: knob(true, "default", "bool"),
  stall_limit: knob(3, "default"),
  stream_reasoning: CORE_knob(true, "default", "bool"),
  sandbox_install_network: {
    value: "bridge",
    source: "default",
    kind: "str",
    env: "MOSAERA_SANDBOX_INSTALL_NETWORK",
    choices: ["bridge", "host", "none"],
  },
};

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/auth/status")) return Promise.resolve(jsonResponse(ADMIN));
      if (url.includes("/api/settings/general")) return Promise.resolve(jsonResponse({ knobs: KNOBS }));
      if (url.includes("/api/features")) return Promise.resolve(jsonResponse({ delete_tool_enabled: false }));
      return Promise.resolve(jsonResponse({}));
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={["/settings/general"]}>
          <Routes>
            <Route path="/settings/:section" element={children} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}

describe("SettingsPage", () => {
  it("renders the section nav for an admin", async () => {
    render(<SettingsPage />, { wrapper });
    // The left rail lists every section (admin sees Users too).
    for (const label of ["Behavior", "General", "Models", "Git", "Users", "Autonomy", "Advanced"]) {
      expect(await screen.findByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("surfaces the previously-unreachable autonomy knobs, with mr_granularity as a dropdown", async () => {
    // #36: the autonomy cluster + mr_granularity had no Settings home. The Autonomy section now
    // renders them from GENERAL_KNOBS — enum values as <Select> (the hard rule), never free text.
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/api/auth/status")) return Promise.resolve(jsonResponse(ADMIN));
        if (url.includes("/api/settings/general"))
          return Promise.resolve(
            jsonResponse({
              knobs: {
                autonomous_verified: knob(true, "default", "bool", "X", "core"),
                // Posture-clamped ON for every autonomous run, so the toggle was never a real
                // choice. It is now `internal` and must not render at all — removing an inert
                // control beats explaining why it is inert (ADR-0122 §6).
                oracle_coverage: {
                  ...knob(false, "stored", "bool", "X", "internal"),
                  clamped_by: "autonomous_verified",
                },
                mr_granularity: {
                  value: "item",
                  source: "default",
                  kind: "str",
                  env: "MOSAERA_MR_GRANULARITY",
                  choices: ["item", "project"],
                  visibility: "core",
                },
                member_branch_delete: knob(false, "default", "bool"),
              },
            }),
          );
        if (url.includes("/api/features"))
          return Promise.resolve(jsonResponse({ delete_tool_enabled: false }));
        return Promise.resolve(jsonResponse({}));
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <MemoryRouter initialEntries={["/settings/autonomy"]}>
            <Routes>
              <Route path="/settings/:section" element={<SettingsPage />} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>,
    );
    // The two CORE decisions are on the page with nothing to open.
    expect(await screen.findByText("Verify autonomous runs")).toBeInTheDocument();
    // The posture-clamped oracle toggle is GONE, not merely tucked away: it is `internal`, so it
    // is absent even with the disclosure open. This assertion is the guard on that intent — a
    // knob quietly reclassified back to `developer` would resurface here.
    expect(screen.queryByText("Coverage oracle")).not.toBeInTheDocument();
    expect(screen.queryByText("forced when autonomous")).not.toBeInTheDocument();
    // ...and the one enum knob renders as a dropdown, not a typo-able text box.
    const mrg = screen.getByLabelText("Merge-request granularity");
    expect(mrg.tagName).not.toBe("INPUT");
    expect(
      screen.queryByRole("textbox", { name: "Merge-request granularity" }),
    ).not.toBeInTheDocument();
    // Redundancy audit 2026-08-22: `member_branch_delete` MOVED here from the Delivery page — a
    // global knob edited on a project-scoped operations surface silently changed every other
    // project. This is still its only render, so this assertion is the knob's only guard. It is
    // `developer`, not `internal`, on purpose: hiding it outright would remove an admin's only
    // way to grant the permission, which is a regression rather than a simplification.
    await revealAdvanced();
    expect(screen.getByText("Branch destruction")).toBeInTheDocument();
    expect(screen.getByLabelText("Members may delete branches")).toBeEnabled();
  });

  it("renders the General knob form and marks env-pinned fields read-only", async () => {
    render(<SettingsPage />, { wrapper });
    // A General field label + its grouped sub-heading.
    expect(await screen.findByText("Max spend per run")).toBeInTheDocument();
    expect(screen.getByText("Run budgets")).toBeInTheDocument();
    // #37: the daily run quota is now reachable (a number field, not a dropdown), beside the budgets.
    expect(screen.getByLabelText("Runs per day (quota)")).not.toBeDisabled();
    // run_max_usd is pinned by an env var → read-only, badged.
    expect(screen.getByText("set via env")).toBeInTheDocument();
    const pinned = screen.getByLabelText("Max spend per run") as HTMLInputElement;
    expect(pinned).toBeDisabled();
    // A mechanics knob is NOT on the front page any more (ADR-0122 §6) — it is behind the
    // disclosure, and still editable once opened.
    expect(screen.queryByLabelText("Default max iterations")).not.toBeInTheDocument();
    await revealAdvanced();
    expect(screen.getByLabelText("Default max iterations")).not.toBeDisabled();
  });

  it("uses a dropdown (not a text box) for the enumerable install-network setting", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <MemoryRouter initialEntries={["/settings/advanced"]}>
            <Routes>
              <Route path="/settings/:section" element={<SettingsPage />} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>,
    );
    // The field exists, shows the current value, and is NOT a free-text box (no typos).
    await revealAdvanced();
    expect(await screen.findByText("Install network")).toBeInTheDocument();
    const control = screen.getByLabelText("Install network");
    expect(control.tagName).not.toBe("INPUT");
    expect(screen.queryByRole("textbox", { name: "Install network" })).not.toBeInTheDocument();
  });

  it("renders a dropdown for ANY knob the server marks with choices, even a text FieldSpec", async () => {
    // The Hard Rule (M5): the server's `choices` is the source of truth — a knob that gains
    // choices but whose FieldSpec forgot widget:"select" must still be a dropdown, never a
    // typo-able text box. Here the FieldSpec is `text` yet the knob-view carries choices.
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/api/auth/status")) return Promise.resolve(jsonResponse(ADMIN));
        if (url.includes("/api/settings/general"))
          return Promise.resolve(
            jsonResponse({
              knobs: {
                mr_granularity: {
                  value: "item",
                  source: "default",
                  kind: "str",
                  env: "MOSAERA_MR_GRANULARITY",
                  choices: ["item", "project"],
                  visibility: "core",
                },
                member_branch_delete: knob(false, "default", "bool"),
              },
            }),
          );
        return Promise.resolve(jsonResponse({}));
      }),
    );
    const groups = [
      { title: "Delivery", fields: [{ field: "mr_granularity", label: "MR granularity", widget: "text" as const }] },
    ];
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <KnobForm title="Delivery" groups={groups} />
        </AuthProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("MR granularity")).toBeInTheDocument();
    const control = screen.getByLabelText("MR granularity");
    expect(control.tagName).not.toBe("INPUT"); // a Select trigger, not a free-text Input
    expect(screen.queryByRole("textbox", { name: "MR granularity" })).not.toBeInTheDocument();
  });
});
