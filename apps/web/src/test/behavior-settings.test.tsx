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

function profile(value: string | null) {
  return {
    value,
    source: value === null ? "default" : "stored",
    kind: "opt_str",
    env: "MOSAERA_X_PROFILE",
    choices: ["cautious", "balanced", "persistent"],
    visibility: "core",
  };
}

// The shape the API serves: what each option DOES, in sentences, so the page never keeps its own
// copy of the derivation tables.
const CATALOGUE = {
  effort_profile: {
    cautious: [
      { field: "max_reason_attempts", value: 0, effect: "How many times it may stop and reason" },
      { field: "escalate_arm", value: false, effect: "Escalates to a stronger model when stalled" },
    ],
    balanced: [
      { field: "max_reason_attempts", value: 1, effect: "How many times it may stop and reason" },
      { field: "escalate_arm", value: false, effect: "Escalates to a stronger model when stalled" },
    ],
    persistent: [
      { field: "max_reason_attempts", value: 3, effect: "How many times it may stop and reason" },
      { field: "escalate_arm", value: true, effect: "Escalates to a stronger model when stalled" },
    ],
  },
};

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function stub(body: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/auth/status")) return Promise.resolve(jsonResponse(ADMIN));
      if (url.includes("/api/settings/general")) return Promise.resolve(jsonResponse(body));
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
  it("offers THREE intent profiles as dropdowns, never free text", async () => {
    // Three, not four: `autonomy` and `recovery` both answered "how hard does it try?".
    stub({
      knobs: {
        effort_profile: profile(null),
        quality_profile: profile(null),
        verification_profile: profile(null),
      },
    });
    render(<BehaviorSettings />, { wrapper });
    for (const label of ["Effort", "Quality bar", "Independent verification"]) {
      expect(await screen.findByRole("combobox", { name: label })).toBeInTheDocument();
    }
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("shows what each option DOES, in sentences rather than knob identifiers", async () => {
    // The theatre this fixes: a row reading `max_reason_attempts: 3` predicts nothing for the
    // reader. The comparison must carry the effect sentence and the differing values.
    stub({ knobs: { effort_profile: profile("balanced") }, profiles: CATALOGUE });
    render(<BehaviorSettings />, { wrapper });

    const table = await screen.findByRole("table");
    expect(within(table).getByText(/How many times it may stop and reason/)).toBeInTheDocument();
    // Every option is shown against the others, so the choice is a comparison, not a guess.
    for (const c of ["cautious", "persistent"]) {
      expect(within(table).getByText(c)).toBeInTheDocument();
    }
    const row = within(table).getByText(/How many times it may stop/).closest("tr")!;
    expect(within(row).getByText("0")).toBeInTheDocument();
    expect(within(row).getByText("3")).toBeInTheDocument();
    // The selected option is marked, so "which am I on?" needs no cross-reference.
    expect(within(table).getByText("selected")).toBeInTheDocument();
  });

  it("hides a setting that is identical across every option", async () => {
    // A row the same in all options is noise that buries the decision the reader came to make.
    stub({
      knobs: { effort_profile: profile("balanced") },
      profiles: {
        effort_profile: {
          cautious: [
            { field: "same_everywhere", value: 5, effect: "Never varies" },
            { field: "differs", value: 1, effect: "Does vary" },
          ],
          balanced: [
            { field: "same_everywhere", value: 5, effect: "Never varies" },
            { field: "differs", value: 2, effect: "Does vary" },
          ],
        },
      },
    });
    render(<BehaviorSettings />, { wrapper });
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Does vary")).toBeInTheDocument();
    expect(within(table).queryByText("Never varies")).not.toBeInTheDocument();
  });

  it("says which of a profile's settings the operator has overridden", async () => {
    // Otherwise the comparison promises something this deployment is not doing.
    stub({
      knobs: {
        effort_profile: profile("persistent"),
        max_reason_attempts: {
          value: 0,
          source: "stored",
          kind: "int",
          env: "M",
          derived_from: "effort_profile",
        },
      },
      profiles: CATALOGUE,
    });
    render(<BehaviorSettings />, { wrapper });
    const table = await screen.findByRole("table");
    expect(within(table).getByText(/you set this to 0/i)).toBeInTheDocument();
  });

  it("names what no profile can change", async () => {
    // Effort changes how hard a run tries, never what evidence it must produce.
    stub({
      knobs: { effort_profile: profile("balanced") },
      constant: ["deliver_unverified", "scan_enabled"],
    });
    render(<BehaviorSettings />, { wrapper });
    const section = await screen.findByRole("region", { name: "What no profile changes" });
    expect(within(section).getByText("deliver_unverified")).toBeInTheDocument();
    expect(within(section).getByText("scan_enabled")).toBeInTheDocument();
  });

  it("badges profile provenance on the mechanics knobs themselves", async () => {
    stub({
      knobs: {
        max_iterations_ceiling: {
          value: 8,
          source: "profile",
          kind: "int",
          env: "MOSAERA_MAX_ITERATIONS_CEILING",
          derived_from: "effort_profile",
        },
        max_reason_attempts: {
          value: 5,
          source: "stored",
          kind: "int",
          env: "M",
          derived_from: "effort_profile",
        },
      },
    });
    render(
      <KnobForm
        title="Mechanics"
        groups={[
          {
            title: "Loops",
            fields: [
              { field: "max_iterations_ceiling", label: "Ceiling", widget: "number" },
              { field: "max_reason_attempts", label: "Reason attempts", widget: "number" },
            ],
          },
        ]}
      />,
      { wrapper },
    );
    // Mechanics knobs sit behind the disclosure; the badges must survive that trip.
    expect(screen.queryByText(/^from Effort$/)).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Show advanced configuration/ }));
    expect(await screen.findByText(/^from Effort$/)).toBeInTheDocument();
    expect(screen.getByText(/^overrides Effort$/)).toBeInTheDocument();
  });

  it("drops an internal knob entirely, and counts the advanced ones it hides", async () => {
    stub({
      knobs: {
        auto_open_mr: {
          value: true,
          source: "default",
          kind: "bool",
          env: "A",
          visibility: "core",
        },
        sandbox_timeout: {
          value: 300,
          source: "default",
          kind: "int",
          env: "S",
          visibility: "developer",
        },
        deliver_unverified: {
          value: false,
          source: "default",
          kind: "bool",
          env: "D",
          visibility: "internal",
        },
      },
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
    fireEvent.click(screen.getByRole("button", { name: "Show advanced configuration (1)" }));
    expect(screen.getByText("Sandbox timeout")).toBeInTheDocument();
    // The gate bypass is not reachable from the UI at any depth.
    expect(screen.queryByText("Deliver unverified")).not.toBeInTheDocument();
  });

  it("shows Not saved with the field and why, instead of a blanket Saved (#task-9/S4)", async () => {
    // The PUT response now names a field it did NOT apply; the client must say so rather than
    // clearing every edit as if the whole patch had gone through.
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/api/auth/status")) return Promise.resolve(jsonResponse(ADMIN));
        if (url.includes("/api/settings/general")) {
          if (init?.method === "PUT") {
            return Promise.resolve(
              jsonResponse({
                knobs: { sandbox_timeout: { value: 300, source: "default", kind: "int", env: "S" } },
                rejected: { sandbox_timeout: "blank or invalid value — left unchanged" },
              }),
            );
          }
          return Promise.resolve(
            jsonResponse({
              knobs: {
                sandbox_timeout: { value: 300, source: "default", kind: "int", env: "S", visibility: "core" },
              },
            }),
          );
        }
        return Promise.resolve(jsonResponse({}));
      }),
    );
    render(
      <KnobForm
        title="General"
        groups={[
          { title: "G", fields: [{ field: "sandbox_timeout", label: "Sandbox timeout", widget: "number" }] },
        ]}
      />,
      { wrapper },
    );
    const input = await screen.findByLabelText("Sandbox timeout");
    fireEvent.change(input, { target: { value: "600" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Not saved — sandbox_timeout: blank or invalid value/)).toBeInTheDocument();
  });

});
