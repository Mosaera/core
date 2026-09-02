import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunDiagnosis } from "../api/client";
import { RunDiagnosisCard } from "../components/runs/RunDiagnosisCard";

/* How a run ENDED (#75). Until this existed a finished run showed one 80-character line, so a
   failure on this screen could not be compared against the same failure last week. */

const park: RunDiagnosis = {
  outcome: "honest_park",
  park_cause: "give_up",
  gate_reasons: ["validation_failed", "unsatisfied_claim"],
  give_up_reason: "no convergence: failing count 4 -> 4 -> 4",
  vouch: "no_vouch:not_behavior_preserving",
  unsatisfied_claims: ["task-c16"],
  iteration: 6,
  max_iterations: 6,
};

describe("RunDiagnosisCard", () => {
  it("leads with why the run stopped, not with what the gate wanted", () => {
    render(<RunDiagnosisCard diagnosis={park} />);
    // The stop channel is the run's real reason; the gate's reasons describe what was missing at
    // the door. A reader wants the first one first.
    expect(screen.getByText(/no convergence: failing count 4/)).toBeInTheDocument();
    expect(screen.getByText(/Stopped honestly, without delivering/)).toBeInTheDocument();
  });

  it("shows the raw bucket alongside the plain reading", () => {
    // The plain wording is for a human; the token is what the benchmark and the logs use. Dropping
    // it would make this screen uncomparable with every other record of the same run.
    render(<RunDiagnosisCard diagnosis={park} />);
    expect(screen.getByText("honest_park")).toBeInTheDocument();
    expect(screen.getByText("give_up")).toBeInTheDocument();
    // The park cause gets its plain sentence too (shared lib/plain deck).
    expect(screen.getByText(/couldn't finish this and stopped honestly/)).toBeInTheDocument();
  });

  it("renders every gate reason, and the unverified claims behind them", () => {
    render(<RunDiagnosisCard diagnosis={park} />);
    // Rendered through the shared plain-language layer (lib/plain.ts), so this screen speaks the
    // same words as the gate panel and the receipt rather than inventing a third vocabulary.
    expect(screen.getByText(/the automated checks failed/)).toBeInTheDocument();
    expect(screen.getByText(/not every claim was verified/)).toBeInTheDocument();
    expect(screen.getByText(/task-c16/)).toBeInTheDocument();
    expect(screen.getByText("iteration 6/6")).toBeInTheDocument();
  });

  it("surfaces the stop channels that used to be invisible", () => {
    // `blocked_reason` and `escalate_reason` exist because a park on 2026-08-05 was declined for a
    // reason NOTHING recorded — these were the only candidates left, neither was persisted, and
    // the cause is permanently unrecoverable.
    render(
      <RunDiagnosisCard
        diagnosis={{ outcome: "honest_park", blocked_reason: "missing dependency" }}
      />,
    );
    expect(screen.getByText(/missing dependency/)).toBeInTheDocument();
    expect(screen.getByText(/Coder blocked/)).toBeInTheDocument();
  });

  it("renders a sparse record without inventing the missing parts", () => {
    // A pre-0022 row or a partial terminal path. Absent stays absent: the value of this screen is
    // that a reader can trust it three days later.
    render(<RunDiagnosisCard diagnosis={{ outcome: "clean_deliver" }} />);
    expect(screen.getByText("Delivered")).toBeInTheDocument();
    expect(screen.queryByText(/Blocked at the gate by/)).not.toBeInTheDocument();
    expect(screen.queryByText(/unverified claims/)).not.toBeInTheDocument();
  });

  it("flags a tamper in red rather than burying it in the token list", () => {
    render(
      <RunDiagnosisCard diagnosis={{ outcome: "thrash_park", tests_modified: true }} />,
    );
    expect(screen.getByText("tests modified")).toBeInTheDocument();
  });
});

describe("what to DO about it (#121)", () => {
  it("names the remedy beside the reason", () => {
    // #108 made the cause visible and left the reader with no next step — for someone who has not
    // read the docs, a diagnosis with no action is the same dead end it replaced.
    render(<RunDiagnosisCard diagnosis={park} />);
    expect(screen.getByText(/send it back to revise/i)).toBeInTheDocument();
  });

  it("specialises the oracle remedy by WHICH leg refused", () => {
    // `oracle_blocked_by` has been recorded on every run since #60 and was never rendered, so one
    // generic sentence covered three situations with different answers.
    render(
      <RunDiagnosisCard
        diagnosis={{
          outcome: "honest_park",
          gate_reasons: ["oracle_unverified"],
          oracle_blocked_by: ["mutation"],
        }}
      />,
    );
    expect(screen.getByText(/deliberately broke the code/i)).toBeInTheDocument();
    // ...and does NOT tell them to flip the Proctor, which may already be on.
    expect(screen.queryByText(/Turn the Proctor on/i)).not.toBeInTheDocument();
  });

  it("falls back to the independence remedy when no leg was recorded", () => {
    render(
      <RunDiagnosisCard
        diagnosis={{ outcome: "honest_park", gate_reasons: ["oracle_unverified"] }}
      />,
    );
    expect(screen.getByText(/Turn the Proctor on/i)).toBeInTheDocument();
    expect(screen.getByText("(tester_enabled)")).toBeInTheDocument(); // the real knob, named
  });

  it("says nothing for a reason with no remedy on file", () => {
    render(<RunDiagnosisCard diagnosis={{ outcome: "honest_park", gate_reasons: ["from_the_future"] }} />);
    expect(screen.getByText(/from the future/)).toBeInTheDocument(); // the reason still renders
    expect(screen.queryByRole("list")).not.toBeInTheDocument(); // no invented advice
  });
});
