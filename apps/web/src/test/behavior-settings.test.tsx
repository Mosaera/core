import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../api/authContext";
import { BehaviorSettings } from "../components/settings/BehaviorSettings";
import { KnobForm } from "../components/settings/KnobForm";

const ADMIN = {
  users_supported: true,
  needs_setup: false,
  auth_required: true,
  user: { id: 1, username: "alex", is_admin: true },
};

function profile(value: string | null, source = "stored") {
  return {
    value,
    source: value === null ? "default" : source,
    kind: "opt_str",
    env: "MOSAERA_X_PROFILE",
    choices: ["conservative", "balanced", "aggressive"],
    visibility: "core",
  };
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function stub(knobs: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/auth/status")) return Promise.resolve(jsonResponse(ADMIN));
      if (url.includes("/api/settings/general")) return Promise.resolve(jsonResponse({ knobs }));
      return Promise.resolve(jsonResponse({}));
    }),
  );
}

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("BehaviorSettings (ADR-0122)", () => {
  it("renders every intent profile as a dropdown, never free text", async () => {
    // The hard rule: an enumerable value is a <Select> built from the server's `choices`.
    stub({
      autonomy_profile: profile(null),
      recovery_profile: profile(null),
      quality_profile: profile(null),
      verification_profile: profile(null),
    });
    render(<BehaviorSettings />, { wrapper });
    for (const label of ["Autonomy", "Recovery effort", "Quality bar", "Independent verification"]) {
      expect(await screen.findByRole("combobox", { name: label })).toBeInTheDocument();
    }
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("says nothing is overwritten when no profile is selected", async () => {
    stub({ autonomy_profile: profile(null), max_iterations: { ...profile(null), value: 8 } });
    render(<BehaviorSettings />, { wrapper });
    expect(await screen.findByText(/No profile is selected/i)).toBeInTheDocument();
    expect(screen.getByText(/nothing you configured by hand is overwritten/i)).toBeInTheDocument();
  });

  it("attributes a derived value to its profile, and marks one an explicit setting overrides", async () => {
    // The two things provenance must distinguish. Reporting only the first would hide the case an
    // operator actually hunts for: a profile that looks selected but is not in effect here.
    stub({
      autonomy_profile: profile("conservative"),
      // Supplied BY the profile.
      max_iterations_ceiling: {
        value: 8,
        source: "profile",
        kind: "int",
        env: "MOSAERA_MAX_ITERATIONS_CEILING",
        derived_from: "autonomy_profile",
      },
      // Owned by the profile but explicitly set — the explicit value wins.
      max_iterations: {
        value: 5,
        source: "stored",
        kind: "int",
        env: "MOSAERA_MAX_ITERATIONS",
        derived_from: "autonomy_profile",
      },
    });
    render(<BehaviorSettings />, { wrapper });

    // Await the POPULATED summary specifically: the empty state shares its title, so awaiting the
    // region alone resolves against the still-loading render.
    await screen.findByText("max_iterations_ceiling");
    const summary = screen.getByRole("region", { name: "What your profiles set" });
    // Both knobs are listed under the profile that owns them, with the profile's selected value.
    expect(within(summary).getByText("max_iterations_ceiling")).toBeInTheDocument();
    expect(within(summary).getByText("conservative")).toBeInTheDocument();

    // Only the overridden one is flagged, and it shows the value that actually wins. Scoped to
    // the list — the section's own description says the word "overridden" too.
    const rows = within(summary).getByRole("list");
    expect(within(rows).getAllByText(/^overridden$/i)).toHaveLength(1);
    const row = within(rows).getByText("max_iterations").closest("li")!;
    expect(within(row).getByText("5")).toBeInTheDocument();
    expect(within(row).getByText(/^overridden$/i)).toBeInTheDocument();
  });

  it("badges the same provenance on the mechanics knobs themselves", async () => {
    // The summary is not the only place this must show: an operator reading the Autonomy page
    // needs to know a value came from a profile without navigating away to find out.
    stub({
      max_iterations_ceiling: {
        value: 8,
        source: "profile",
        kind: "int",
        env: "MOSAERA_MAX_ITERATIONS_CEILING",
        derived_from: "autonomy_profile",
      },
      max_iterations: {
        value: 5,
        source: "stored",
        kind: "int",
        env: "MOSAERA_MAX_ITERATIONS",
        derived_from: "autonomy_profile",
      },
    });
    render(
      <KnobForm
        title="Autonomy"
        groups={[
          {
            title: "Iterations",
            fields: [
              { field: "max_iterations_ceiling", label: "Ceiling", widget: "number" },
              { field: "max_iterations", label: "Default max iterations", widget: "number" },
            ],
          },
        ]}
      />,
      { wrapper },
    );
    // Both are mechanics knobs, so they sit behind the disclosure — and the badges must survive
    // that trip, which is the case a flat render would not have covered.
    expect(screen.queryByText(/^from Autonomy$/)).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Show advanced configuration/ }));
    expect(await screen.findByText(/^from Autonomy$/)).toBeInTheDocument();
    expect(screen.getByText(/^overrides Autonomy$/)).toBeInTheDocument();
  });

  it("drops an internal knob entirely, and counts the advanced ones it hides", async () => {
    // The hide slice's core claim (ADR-0122 §6): `internal` is absent even with the disclosure
    // open, `developer` is reachable but not on the front page, `core` needs no opening.
    stub({
      auto_open_mr: { ...profile(null), value: true, kind: "bool", choices: null },
      sandbox_timeout: { value: 300, source: "default", kind: "int", env: "S", visibility: "developer" },
      deliver_unverified: { value: false, source: "default", kind: "bool", env: "D", visibility: "internal" },
    });
    render(
      <KnobForm
        title="Mixed"
        groups={[
          {
            title: "All three",
            fields: [
              { field: "auto_open_mr", label: "Open MRs automatically", widget: "toggle" },
              { field: "sandbox_timeout", label: "Sandbox timeout", widget: "number" },
              { field: "deliver_unverified", label: "Deliver unverified", widget: "toggle" },
            ],
          },
        ]}
      />,
      { wrapper },
    );
    expect(await screen.findByText("Open MRs automatically")).toBeInTheDocument();
    expect(screen.queryByText("Sandbox timeout")).not.toBeInTheDocument();
    // The count tells the operator what is behind the disclosure before they open it.
    fireEvent.click(screen.getByRole("button", { name: "Show advanced configuration (1)" }));
    expect(screen.getByText("Sandbox timeout")).toBeInTheDocument();
    // The gate bypass is not reachable from the UI at any depth.
    expect(screen.queryByText("Deliver unverified")).not.toBeInTheDocument();
  });
});
