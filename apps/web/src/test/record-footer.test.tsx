import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { RunDetail } from "../api/client";
import { deriveLedger, type LedgerRow } from "../lib/ledger";
import { RecordFooter } from "../components/runs/RecordFooter";

function detail(over: Partial<RunDetail> = {}): RunDetail {
  return {
    id: "r1", task: "t", status: "APPROVED", tests_passed: true, iterations: 1,
    commit_sha: "abc", source: "s", branch: "b", project_id: "p1", item_id: null,
    created_at: "2026-08-03T09:00:00Z", decisions: [], test_results: [], repo_changes: [],
    approvals: [], ...over,
  };
}

const RECEIPT_ROW = {
  kind: "receipt",
  content: JSON.stringify({
    action: "deliver", reasons: [], reviewer_verdict: "APPROVE", tests_passed: true,
    oracle_verified: true, validation_strength: "suite", unsatisfied_claims: [],
    human_override: false, oracle_vouched_by: "", oracle_residual: "",
    tests_mutation_caught: true,
  }),
  created_at: null,
};

function sealOf(d: RunDetail) {
  const rows = deriveLedger({ detail: d });
  return (rows.find((r) => r.kind === "seal") ?? null) as
    | Extract<LedgerRow, { kind: "seal" }>
    | null;
}

function renderFooter(d: RunDetail) {
  return render(
    <MemoryRouter>
      <RecordFooter rid={d.id} seal={sealOf(d)} detail={d} />
    </MemoryRouter>,
  );
}

async function realId(runId: string, commit: string, version: string, payload: string) {
  const { createHash } = await import("node:crypto");
  return createHash("sha256")
    .update(`${runId}\n${commit}\n${version}\n${payload}`)
    .digest("hex");
}

describe("RecordFooter", () => {
  it("renders the facts grid + checksum with stamped values", async () => {
    const receiptId = await realId("r1", "abc", "0.6.0", RECEIPT_ROW.content);
    renderFooter(
      detail({
        decisions: [
          RECEIPT_ROW,
          { kind: "quality", content: JSON.stringify({ composite: 84, dimensions: [] }), created_at: null },
        ],
        repo_changes: [{ diff: "diff --git a/x b/x\n@@ -1 +1 @@\n-a\n+b", commit_sha: "abc", created_at: null }],
        finished_at: "2026-08-03T12:00:00Z",
        engine_version: "0.6.0",
        receipt_id: receiptId,
      }),
    );
    expect(screen.getByText(/sha256 · /)).toBeInTheDocument();
    expect(screen.getByText("abc")).toBeInTheDocument(); // commit
    expect(screen.getByText("84/100 advisory")).toBeInTheDocument();
    expect(screen.getByText("v0.6.0")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /download patch/ })).toBeInTheDocument();
    // Verify recomputes in-browser and confirms the intact record.
    fireEvent.click(screen.getByRole("button", { name: "Verify checksum" }));
    expect(await screen.findByText(/Verified — the record is intact/)).toBeInTheDocument();
  });

  it("a tampered record fails verification honestly", async () => {
    const receiptId = await realId("r1", "tampered-commit", "0.6.0", RECEIPT_ROW.content);
    renderFooter(
      detail({
        decisions: [RECEIPT_ROW],
        finished_at: "2026-08-03T12:00:00Z",
        engine_version: "0.6.0",
        receipt_id: receiptId,
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Verify checksum" }));
    expect(await screen.findByText(/Checksum mismatch/)).toBeInTheDocument();
  });

  it("never-stamped inputs report uncomputable, never a verdict", async () => {
    renderFooter(
      detail({
        decisions: [], // no receipt payload
        finished_at: "2026-08-03T12:00:00Z",
        engine_version: "0.6.0",
        receipt_id: "ab".padEnd(64, "0"),
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Verify checksum" }));
    expect(
      await screen.findByText(/Can't verify — this record predates the checksum inputs/),
    ).toBeInTheDocument();
  });

  it("null stamps render honestly — never proxied", () => {
    renderFooter(detail({ status: "NOT APPROVED" }));
    expect(screen.getByText("No checksum was recorded for this run.")).toBeInTheDocument();
    expect(screen.getByText("version not recorded")).toBeInTheDocument();
  });
});
