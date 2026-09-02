import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GatePayload } from "../api/client";
import { BudgetGate } from "../components/runs/BudgetGate";
import { GatePanel } from "../components/runs/GatePanel";
import { DecisionHero } from "../components/runs/hero/DecisionHero";

/** A budget park must never be offered in delivery verbs.
 *
 * Found live 2026-08-21 and confirmed by audit: `RunWorkbench` rendered `GatePanel` for ANY gate
 * action, and `GatePanel` has no budget branch — so a budget park fell through to its legacy
 * buttons, "Approve & deliver" and "Send back", while `DecisionHero` above it correctly routed to
 * `BudgetGate`. The same paused run told two different stories, and the dock's was wrong in both
 * directions: approving GRANTS ANOTHER BUDGET'S WORTH and continues (`runner/_budget.py`), and
 * "Send back" is a denial, which terminally CANCELS the run and discards the work.
 *
 * The fix routes the dock by action exactly as the hero does. These tests pin the property that
 * matters — the two surfaces agree — rather than either one's markup. */

const BUDGET: GatePayload = {
  action: "budget",
  breach: "tokens",
  spent: 202215,
  cap: 200000,
} as GatePayload;

describe("budget park routing", () => {
  it("offers continue/stop, never deliver/send-back", () => {
    render(<BudgetGate gate={BUDGET} busy={false} onDecide={() => {}} variant="hero" />);
    expect(screen.getByText(/Continue — raise limit/)).toBeInTheDocument();
    expect(screen.getByText(/Stop run/)).toBeInTheDocument();
    expect(screen.queryByText(/Approve & deliver/)).toBeNull();
    expect(screen.queryByText(/Send back/)).toBeNull();
  });

  it("the hero routes a budget payload to the budget surface", () => {
    render(
      <DecisionHero gate={BUDGET} flavor="budget" busy={false} onDecide={() => {}} />,
    );
    expect(screen.getByText(/Continue — raise limit/)).toBeInTheDocument();
  });

  it("GatePanel really would mislabel it — which is WHY routing is the fix", () => {
    // Not a wish for GatePanel to grow a budget branch: this asserts the hazard is real, so that
    // if someone later points the dock back at GatePanel the reason is on the record. If GatePanel
    // ever does learn budgets, this test should be deleted deliberately, not silently.
    render(<GatePanel gate={BUDGET} busy={false} onDecide={() => {}} variant="hero" />);
    expect(screen.queryByText(/Continue — raise limit/)).toBeNull();
  });
});
