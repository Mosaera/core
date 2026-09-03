import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RunDetail } from "../api/client";
import { RunHistoryView } from "../components/runs/RunHistoryView";

const config = vi.fn();
const transcript = vi.fn();
const getProject = vi.fn();
vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      config: () => config(),
      patchUrl: (id: string) => `/patch/${id}`,
      transcript: (id: string) => transcript(id),
      getProject: (id: string) => getProject(id),
    },
  };
});

function detail(over: Partial<RunDetail> = {}): RunDetail {
  return {
    id: "r1",
    task: "Build the hero",
    status: "APPROVED",
    tests_passed: true,
    iterations: 2,
    commit_sha: "deadbeef1234",
    source: "s",
    branch: "mosaera/r1",
    project_id: null,
    item_id: null,
    validation_status: "pass",
    created_at: null,
    decisions: [
      { kind: "summary", content: "## What I did\n\n- **wrote** the footer\n- ran tests", created_at: null },
      { kind: "plan", content: "1. read index.html\n2. add a footer", created_at: null },
      { kind: "design", content: "## Approach\n\nReuse the existing footer partial.", created_at: null },
      { kind: "review", content: "VERDICT: APPROVE\n\nLooks good.", created_at: null },
    ],
    test_results: [{ passed: true, output: "3 passed", created_at: null }],
    repo_changes: [
      { diff: "diff --git a/x b/x\n@@ -1 +1 @@\n-old\n+new", commit_sha: "deadbeef", created_at: null },
    ],
    approvals: [],
    ...over,
  };
}

function renderView(d = detail()) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <RunHistoryView detail={d} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  config.mockResolvedValue({ gitlab: false });
  transcript.mockResolvedValue({
    run_id: "r1", status: "APPROVED", termination_reason: null, task: "t", events: [],
  });
  getProject.mockResolvedValue({ backlog: [] });
});

describe("RunHistoryView", () => {
  it("shows the summary rendered as markdown (not raw syntax)", async () => {
    renderView();
    // The summary decision renders as markdown: `## What I did` is a heading
    // element and `**wrote**` a <strong> — NOT literal markdown text.
    expect(await screen.findByRole("heading", { name: "What I did" })).toBeInTheDocument();
    expect(screen.getByText("wrote").tagName).toBe("STRONG");
    expect(screen.queryByText(/## What I did/)).not.toBeInTheDocument();
  });

  it("renders the diff as primary content, no evidence tabs, and a CTA to the run", async () => {
    renderView();
    // The diff is the page's primary content (line-numbered; the +/- prefix is
    // stripped, so the added line reads "new").
    expect(await screen.findByText("new")).toBeInTheDocument();
    // Run evidence moved off this page — no tabs here.
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    // The run-view CTA links to the full run page (ad-hoc render → /runs/:id).
    expect(screen.getByRole("link", { name: /open in run view/ })).toHaveAttribute(
      "href",
      "/runs/r1",
    );
  });

  it("an unchecked delivery says so honestly (never a green verdict)", async () => {
    renderView(detail({ validation_status: "unavailable" }));
    // Redundancy audit 2026-08-22: the hero's claims-only sentence retired; the receipt-derived
    // card headline is the one verdict render — and for an unchecked delivery it is never
    // "Proven". The band's no-claims line keeps the "nothing was checked" fact in prose.
    expect(await screen.findByText("Delivered.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Proven" })).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Delivered — not fully proven" }),
    ).toBeInTheDocument();
  });

  it("renders the sealed ledger: claims chips, gate account with residual, delivered, seal (#63)", async () => {
    renderView(
      detail({
        decisions: [
          {
            kind: "receipt",
            content: JSON.stringify({
              action: "require_human", reasons: ["oracle_unverified"], reviewer_verdict: "APPROVE",
              tests_passed: true, oracle_verified: false, validation_strength: "suite",
              unsatisfied_claims: [], human_override: true,
              oracle_vouched_by: "structural_claims:c1",
              oracle_residual: "shape: proven · UNPROVEN: a mutation survives",
              tests_mutation_caught: false,
            }),
            created_at: null,
          },
        ],
        claims: [
          {
            claim_id: "c1", text: "keeps the API", verdict: "satisfied",
            oracle_ref: "extract(a)", material: true, provenance: "ENTAILED",
            oracle_kind: "ast_transformation_contract",
          },
        ],
        approvals: [
          { action: "deliver", approved: true, feedback: "accept", created_at: "2026-08-03T11:54:00Z" },
        ],
        finished_at: "2026-08-03T12:00:00Z",
        engine_version: "0.6.0",
        receipt_id: "9f".padEnd(64, "0"),
      }),
    );
    // Redundancy audit 2026-08-22: the hero sentence retired (second verdict derivation); the
    // claim bar's aggregate is now the ONE render of the count (the old "phase stepper echo"
    // comment was stale — no second render existed).
    expect(await screen.findByText("1 of 1 verified")).toBeInTheDocument();
    // The gate row carries the residual account + the human override on record
    expect(screen.getByText(/UNPROVEN: a mutation survives/)).toBeInTheDocument();
    expect(screen.getByText(/chose to deliver despite these warnings/i)).toBeInTheDocument();
    // The verdict band names the claim beside the check it stands on, and says
    // plainly that the delivery was clean (#63 engine composition).
    const verdict = screen.getByRole("region", { name: "Why this delivered" });
    expect(within(verdict).getByText("keeps the API")).toBeInTheDocument();
    expect(within(verdict).getByText("PROVEN")).toBeInTheDocument();
    // The h3 became the DERIVED card headline — and for this fixture that is an upgrade in
    // honesty the old static heading couldn't express: a human override over an unverified
    // oracle is a delivery, but not a proven one. The region keeps its name as the contract.
    expect(
      within(verdict).getByRole("heading", { name: "Delivered — not fully proven" }),
    ).toBeInTheDocument();
    expect(screen.getByText("v0.6.0")).toBeInTheDocument();
  });

  it("a run with no receipt shows the honest unsealed footer", async () => {
    renderView(detail({ status: "NOT APPROVED" }));
    expect(
      await screen.findByText("No checksum was recorded for this run."),
    ).toBeInTheDocument();
  });
});
