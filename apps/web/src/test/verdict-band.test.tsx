import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { RunDetail, RunDiagnosis } from "../api/client";
import { deriveLedger } from "../lib/ledger";
import { parseReceipt } from "../lib/runs";
import { VerdictBand } from "../components/runs/engine/VerdictBand";

const claim = (over: Partial<Record<string, unknown>> = {}) => ({
  claim_id: "c1",
  text: "search ignores case",
  verdict: "satisfied",
  oracle_ref: "test_search_ignores_case",
  material: true,
  provenance: "ENTAILED",
  oracle_kind: "acceptance_test",
  ...over,
});

const RECEIPT = (over: Record<string, unknown> = {}) => ({
  kind: "receipt",
  content: JSON.stringify({
    action: "deliver",
    reasons: [],
    reviewer_verdict: "APPROVE",
    tests_passed: true,
    oracle_verified: true,
    validation_strength: "suite",
    unsatisfied_claims: [],
    human_override: false,
    oracle_vouched_by: "",
    oracle_residual: "",
    tests_mutation_caught: true,
    ...over,
  }),
  created_at: null,
});

function detail(over: Partial<RunDetail> = {}): RunDetail {
  return {
    id: "r1", task: "t", status: "APPROVED", tests_passed: true, iterations: 1,
    commit_sha: "abc12345", source: "s", branch: "b", project_id: "p1", item_id: null,
    created_at: "2026-08-04T02:18:00Z", finished_at: "2026-08-04T02:26:00Z",
    decisions: [RECEIPT()], test_results: [], repo_changes: [], approvals: [],
    claims: [claim()], ...over,
  } as RunDetail;
}

/** The PM page stand-in: proves the CTA lands the prefill in router state. */
function PmProbe() {
  const location = useLocation();
  const prefill = (location.state as { pmPrefill?: string } | null)?.pmPrefill;
  return <div data-testid="pm-probe">{prefill}</div>;
}

const band = (
  d: RunDetail,
  extra: { diagnosis?: RunDiagnosis | null; pmProjectId?: string | null } = {},
) => {
  const rows = deriveLedger({ detail: d });
  return render(
    <MemoryRouter initialEntries={["/runs/r1"]}>
      <Routes>
        <Route
          path="/runs/r1"
          element={
            <VerdictBand
              rows={rows}
              receipt={parseReceipt(d)}
              testCount={3}
              runId={d.id}
              task={d.task}
              {...extra}
            />
          }
        />
        <Route path="/projects/:pid/pm" element={<PmProbe />} />
      </Routes>
    </MemoryRouter>,
  );
};

describe("VerdictBand — delivered", () => {
  it("names each claim beside the check it stands on", () => {
    band(detail());
    expect(screen.getByRole("region", { name: "Why this delivered" })).toBeInTheDocument();
    expect(screen.getByText("search ignores case")).toBeInTheDocument();
    // The claim's own line names the check it stands on (kind + the test id).
    const claimLine = screen.getByText("search ignores case").parentElement!;
    // F67: honest about what actually stands behind it — the suite passing, not a named test.
    expect(claimLine.textContent).toContain("covered by the run's whole suite passing");
    expect(claimLine.textContent).toContain("test_search_ignores_case");
    expect(claimLine.textContent).toContain("FROM YOUR REQUEST");
    expect(screen.getByText("PROVEN")).toBeInTheDocument();
    // The outcome is stated ONCE per page — the heading, not a second pill.
    // De-firehose redesign 2026-08-22: the static h3 became the derived VerdictCard headline —
    // the region name stays as the contract; the visible verdict is now computed, never asserted.
    expect(screen.getByRole("heading", { name: "Proven" })).toBeInTheDocument();
    // Redundancy audit 2026-08-22: the Block header badges ("1 proven") were cut — they summed
    // the pill column directly beneath, which the ClaimRow pills above already carry.
  });

  it("an unchecked claim is amber NOT CHECKED — never green, and the header says so", () => {
    band(
      detail({
        claims: [
          claim(),
          claim({ claim_id: "c2", text: "stays fast on big lists", verdict: "unbound", oracle_ref: "", oracle_kind: "none" }),
        ],
      }),
    );
    // The unchecked claim stands in the open, beside the proven one — per-row pills are the one
    // render of each claim's outcome (the header count badges were cut 2026-08-22; the hero
    // ClaimBar carries the aggregate).
    expect(screen.getByText("NOT CHECKED")).toBeInTheDocument();
    expect(screen.getByText("PROVEN")).toBeInTheDocument();
  });

  it("the proof panel reads the recorded validation strength and sabotage check honestly", () => {
    band(detail());
    const proof = screen.getByText("How strong the proof is").closest("section")!;
    expect(within(proof).getByText("a real test suite ran")).toBeInTheDocument();
    expect(within(proof).getByText(/sabotage caught/)).toBeInTheDocument();
    expect(within(proof).getByText(/network off/)).toBeInTheDocument();
    expect(within(proof).getByText(/never green-light/)).toBeInTheDocument();
  });

  it("a shallow run with an unmeasured sabotage check never claims either", () => {
    band(detail({ decisions: [RECEIPT({ validation_strength: "shallow", tests_mutation_caught: null })] }));
    const proof = screen.getByText("How strong the proof is").closest("section")!;
    expect(within(proof).getByText(/only a syntax-level check ran/)).toBeInTheDocument();
    expect(within(proof).getByText("sabotage check not run")).toBeInTheDocument();
  });

  it("a human override is surfaced, not buried", () => {
    band(detail({ decisions: [RECEIPT({ human_override: true, oracle_residual: "perf unproven" })] }));
    expect(screen.getByText(/chose to deliver despite these warnings/i)).toBeInTheDocument();
    expect(screen.getByText(/Priced residual: perf unproven/)).toBeInTheDocument();
  });
});

describe("VerdictBand — stopped", () => {
  const stopped = detail({
    status: "INCOMPLETE",
    commit_sha: "",
    termination_reason: "no_progress",
    claims: [claim({ verdict: "failed" })],
  });

  it("speaks park language and never delivered language", () => {
    band(stopped);
    expect(screen.getByRole("region", { name: "Why this parked" })).toBeInTheDocument();
    // The ending KIND moved from the h3 to the card's subhead line (same words, still visible);
    // the verdict word itself is derived ("Not proven").
    expect(screen.getByText("Why this parked")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Not proven" })).toBeInTheDocument();
    expect(screen.getByText(/no_progress/)).toBeInTheDocument();
    expect(screen.getByText(/recorded as incomplete — never dressed as “completed”/)).toBeInTheDocument();
    expect(screen.queryByText(/Why this delivered/)).not.toBeInTheDocument();
    expect(screen.queryByText("PROVEN")).not.toBeInTheDocument();
  });

  const LONG_REASON =
    "No convergence — pre-existing/protected tests or their collection config were modified: tests/test_readme_examples.py";
  const DIAGNOSIS: RunDiagnosis = {
    outcome: "thrash_park",
    park_cause: "stalled:plan",
    gate_reasons: ["tests_tampered"],
    unsatisfied_claims: ["c1"],
    stall_reason: LONG_REASON,
  };

  it("with a diagnosis: the FULL uncapped reason and the gate's reasons", () => {
    band(stopped, { diagnosis: DIAGNOSIS });
    // The stopSentence paragraph was cut 2026-08-22 (it restated the hero's status sentence and
    // the card's classified reason); the record ProofRow keeps the uncapped full text.
    // The whole >80-char reason, verbatim — never the capped string, never a fake "…".
    expect(LONG_REASON.length).toBeGreaterThan(80);
    expect(screen.getByText(LONG_REASON)).toBeInTheDocument();
    expect(screen.getByText(/the run modified the tests it was judged by/)).toBeInTheDocument();
    expect(screen.queryByText(/no_progress/)).not.toBeInTheDocument();
  });

  it("Send to Quincy exists only with a project, and lands the park facts in the PM prefill", () => {
    band(stopped, { diagnosis: DIAGNOSIS, pmProjectId: "p1" });
    fireEvent.click(screen.getByRole("button", { name: "Send to Quincy" }));
    const probe = screen.getByTestId("pm-probe");
    expect(probe.textContent).toContain('The run "t" (r1) stopped without delivering.');
    expect(probe.textContent).toContain(LONG_REASON);
    expect(probe.textContent).toContain("Propose how to unblock");
  });

  it("no project → no CTA; no diagnosis → the recorded reason still renders, CTA still works", () => {
    band(stopped, { diagnosis: DIAGNOSIS });
    expect(screen.queryByRole("button", { name: "Send to Quincy" })).not.toBeInTheDocument();
    cleanup();
    band(stopped, { pmProjectId: "p1" });
    expect(screen.getByText(/no_progress/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send to Quincy" })).toBeInTheDocument();
  });

  it("the heading names how the run ended — a crash is never called a park", () => {
    const ended = (status: string) =>
      detail({ status, commit_sha: "", claims: [claim({ verdict: "unbound" })] });
    // De-firehose redesign: the per-status wording moved from the h3 to the card's subhead —
    // the DISTINCTION is the contract (a crash is never called a park), not the element type.
    const kindOf = (text: string) => expect(screen.getByText(text)).toBeInTheDocument();

    band(ended("NOT APPROVED"));
    kindOf("Why this was declined");
    cleanup();
    band(ended("ERROR"));
    kindOf("Why this crashed");
    cleanup();
    band(ended("CANCELLED"));
    kindOf("Why this was cancelled");
    cleanup();
    band(ended("INCOMPLETE"));
    kindOf("Why this parked");
    // ...and never the delivered language, whichever ending it was.
    expect(screen.queryByText(/Why this delivered/)).not.toBeInTheDocument();
  });
});

describe("VerdictBand — live", () => {
  it("renders nothing while the run is still going", () => {
    const rows = deriveLedger({
      detail: detail({ status: "RUNNING", commit_sha: "" }),
      live: { gate: null, status: "running", startedAt: 1 },
    });
    const { container } = render(
      <MemoryRouter>
        <VerdictBand rows={rows} />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
