import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GateDecision, GatePayload } from "../api/client";
import { GatePanel } from "../components/runs/GatePanel";
import { GATE_REASON } from "../lib/plain";

const CLEAR_DECISION: GateDecision = {
  action: "deliver",
  reasons: [],
  tests_passed: true,
  reviewer_verdict: "APPROVE",
};

function gateWith(extra: Partial<GatePayload>): GatePayload {
  return { action: "deliver", gate_decision: CLEAR_DECISION, ...extra };
}

function renderGate(gate: GatePayload) {
  return render(<GatePanel gate={gate} busy={false} onDecide={() => {}} />);
}

describe("GatePanel live-gate honesty", () => {
  it("every gate reason's sentence is readable WITHOUT opening any drawer — ADR-0082 §1", () => {
    // "The summary must contain any fact that would change which option is chosen." The card's
    // dominant reason + chips ARE the summary layer; if a reason's sentence can only be reached by
    // toggling a <details>, this redesign has demoted a fact, not evidence — and must fail here.
    renderGate(
      gateWith({
        gate_decision: {
          action: "require_human",
          reasons: ["oracle_unverified", "reviewer_unknown"],
          tests_passed: true,
          reviewer_verdict: "",
        },
      }),
    );
    const outsideClosedDrawer = (el: HTMLElement): boolean => {
      for (let node: HTMLElement | null = el; node; node = node.parentElement) {
        if (node.tagName === "DETAILS" && !(node as HTMLDetailsElement).open) return false;
      }
      return true;
    };
    for (const token of ["oracle_unverified", "reviewer_unknown"] as const) {
      const els = screen.getAllByText((content) => content.includes(GATE_REASON[token]), {
        selector: "p, span, li, div",
      });
      expect(
        els.some(outsideClosedDrawer),
        `${token} is only reachable inside a closed <details>`,
      ).toBe(true);
    }
  });


  it("never shows a green 'clean' for a scan the gate REFUSED", () => {
    // Red team, 2026-08-21. The clean line was rendered from `gate.findings` alone — the scan
    // TEXT — with no reference to `decision.reasons`. So a run parked precisely BECAUSE its
    // "clean" describes a tree that no longer exists still showed the person holding the override
    // button an unqualified green tick, with the contradiction folded inside a collapsed
    // <details>. ADR-0108 stops the stale verdict vouching to the gate; this stops it vouching to
    // the human, which is the same defect one layer out.
    renderGate(
      gateWith({
        findings: "No security findings.",
        gate_decision: {
          ...CLEAR_DECISION,
          action: "require_human",
          reasons: ["security_stale"],
        },
      }),
    );
    expect(screen.queryByText("clean", { selector: ".text-success" })).not.toBeInTheDocument();
    expect(screen.getByText(/not for this code/)).toBeInTheDocument();
    expect(screen.getByText(/tree changed after the scan ran/)).toBeInTheDocument();
  });

  it("still shows the quiet green line when the scan IS good — the contrast case", () => {
    // Without this, blanking the whole clean line passes the test above.
    renderGate(gateWith({ findings: "No security findings." }));
    expect(screen.getByText("clean")).toBeInTheDocument();
    expect(screen.queryByText(/not for this code/)).not.toBeInTheDocument();
  });

  it("surfaces the stall reason before the human decides", () => {
    renderGate(
      gateWith({ stalled: true, stall_reason: "Validation failed the same way 3 times in a row." }),
    );
    expect(screen.getByText("Couldn't fully complete this")).toBeInTheDocument();
    expect(screen.getByText(/failed the same way 3 times/)).toBeInTheDocument();
  });

  it("surfaces an HONEST EARLY conclusion, which was previously invisible", () => {
    // #56/#81: a run that DIAGNOSED it could not converge and stopped below the cap sets
    // give_up_reason with stalled=False. The banner was gated on `stalled` alone, so the human
    // deciding at the gate saw nothing at all — and #81 moves many more runs onto this path.
    renderGate(
      gateWith({
        give_up_reason:
          "no convergence (no countable result): validation failed identically 3 times — psql: ERROR: relation does not exist",
      }),
    );
    expect(screen.getByText("Stopped early — it couldn't converge")).toBeInTheDocument();
    expect(screen.getByText(/relation does not exist/)).toBeInTheDocument();
  });

  it("prefers the diagnosed give-up reason over a generic stall reason", () => {
    renderGate(
      gateWith({ stalled: true, stall_reason: "generic stall", give_up_reason: "the real diagnosis" }),
    );
    expect(screen.getByText(/the real diagnosis/)).toBeInTheDocument();
    expect(screen.queryByText(/generic stall/)).not.toBeInTheDocument();
  });

  it("labels a delivered-unverified run honestly (never a green checks line)", () => {
    // The ad-hoc "Delivered without checks" badge became the verdict card's checks axis — same
    // honesty rule, one derivation: an unverified delivery must never read as a passing check.
    renderGate(gateWith({ validation_unverified: true }));
    expect(screen.getByText("delivered without a passing validation run")).toBeInTheDocument();
    expect(screen.queryByText("the automated checks passed")).not.toBeInTheDocument();
    expect(screen.queryByText("Checks passed")).not.toBeInTheDocument();
  });

  it("states a passing check on a normal verified delivery", () => {
    renderGate(gateWith({}));
    expect(screen.getByText("the automated checks passed")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't fully complete this")).not.toBeInTheDocument();
  });

  it("shows the priced-residual callout where the human accepts it (#63)", () => {
    renderGate(
      gateWith({
        gate_decision: { ...CLEAR_DECISION, action: "require_human", reasons: ["oracle_unverified"] },
        oracle_vouched_by: "structural_claims:14-c2",
        oracle_residual:
          "shape: proven (structural claim satisfied) · equivalence: passes on all sampled inputs · UNPROVEN: at least one mutation survives",
      }),
    );
    expect(screen.getByText("Known gap — accepted on record")).toBeInTheDocument();
    expect(screen.getByText(/UNPROVEN/)).toBeInTheDocument();
    expect(screen.getByText(/Approving accepts this gap, on record/)).toBeInTheDocument();
    expect(
      screen.getByText(/structure was independently verified to match the request \(14-c2\)/),
    ).toBeInTheDocument();
  });

  it("renders the claims table with honest per-claim verdicts", () => {
    renderGate(
      gateWith({
        claims: [
          { id: "c1", text: "keeps the public API" },
          { id: "c2", text: "sorts stably" },
        ],
        claim_dispositions: [
          { claim_id: "c1", verdict: "satisfied", oracle_ref: "extract_helper(a)" },
          // c2 has no disposition — must render unevaluable, never silently satisfied
        ],
      }),
    );
    expect(screen.getByText("keeps the public API")).toBeInTheDocument();
    expect(screen.getByText("verified")).toBeInTheDocument();
    expect(screen.getByText("extract_helper(a)")).toBeInTheDocument();
    expect(screen.getByText("couldn't be checked")).toBeInTheDocument();
  });

  it("mutation tri-state: null renders 'not run', never a verdict", () => {
    renderGate(gateWith({}));
    expect(screen.getByText(/sabotage check not run/)).toBeInTheDocument();
  });

  // --- the escalation-gate amendment (ADR-0087, #65) ---------------------------------------
  //
  // These exist because the FIRST live escalation crashed this panel to a white screen
  // (2026-08-07). `amendment_offer` returns {} when nothing may be amended, {} is truthy in JS,
  // and `amendable.tests.length` threw. The engine now omits the key entirely AND the panel
  // guards it — but the lesson is that the render path is the one place a thin payload becomes
  // a total failure, so every shape it can arrive in is pinned here.

  it("renders the amendable tests so the operator can authorize one", () => {
    renderGate(
      gateWith({
        amendable: {
          paths: ["tests/test_report.py"],
          tests: ["tests/test_report.py::test_totals_two_lines"],
          criterion: "the summary prints a single combined line",
        },
      }),
    );
    expect(screen.getByText("blocked by a delivered test")).toBeInTheDocument();
    expect(screen.getByText("tests/test_report.py::test_totals_two_lines")).toBeInTheDocument();
    expect(screen.getByText(/single combined line/)).toBeInTheDocument();
  });

  it("does not crash when the offer is an EMPTY object", () => {
    // The live crash, verbatim: {} is truthy, so `amendable.tests.length` threw and the whole
    // gate went blank — the operator could not answer the question the run had just asked.
    renderGate(gateWith({ amendable: {} as never }));
    expect(screen.queryByText("blocked by a delivered test")).not.toBeInTheDocument();
  });

  it("does not crash when the offer has no tests", () => {
    renderGate(gateWith({ amendable: { paths: [], tests: [] } }));
    expect(screen.queryByText("blocked by a delivered test")).not.toBeInTheDocument();
  });

  it("says the linter did not run, rather than showing nothing (#80)", () => {
    renderGate(gateWith({ hygiene_status: "unavailable", hygiene_unavailable: ["mypy"] }));
    expect(screen.getByText("Lint and type checks did not fully run")).toBeInTheDocument();
    expect(screen.getByText(/mypy/)).toBeInTheDocument();
  });

  it("distinguishes 'nothing to check' from 'checked clean' (#80)", () => {
    renderGate(gateWith({ hygiene_status: "not_applicable" }));
    expect(screen.getByText("No lint or type check applied")).toBeInTheDocument();
    expect(screen.getByText(/not the same as passing it/)).toBeInTheDocument();
  });

  it("a clean lint says nothing at all — the callout is for absences only", () => {
    renderGate(gateWith({ hygiene_status: "clean" }));
    expect(screen.queryByText(/did not fully run/)).not.toBeInTheDocument();
    expect(screen.queryByText("No lint or type check applied")).not.toBeInTheDocument();
  });

  it("names the rule that refused an authorized amendment (F71)", () => {
    // The live failure: the operator authorized, the Proctor wrote, every check bit silently, and
    // the run parked on the write as tampering with nothing naming the rule.
    renderGate(
      gateWith({
        amendment_refusals: {
          "tests/test_report.py": "it removed or shrank TestA.test_x (removed), which the operator did not authorize",
        },
      }),
    );
    expect(screen.getByText("Your authorized amendment was refused")).toBeInTheDocument();
    expect(screen.getByText(/did not authorize/)).toBeInTheDocument();
    expect(screen.getByText("tests/test_report.py")).toBeInTheDocument();
  });

  it("shows no refusal callout when nothing was refused", () => {
    renderGate(gateWith({ amendment_refusals: {} }));
    expect(screen.queryByText("Your authorized amendment was refused")).not.toBeInTheDocument();
  });

  it("says WHY the amendment is unavailable instead of showing nothing (F65)", () => {
    renderGate(
      gateWith({
        amendable_withheld:
          "This run already modified a protected test outside the sanctioned channel, so amending one is not offered — the integrity guard's verdict stands.",
      }),
    );
    expect(screen.getByText("Amending a test is not available on this run")).toBeInTheDocument();
    expect(screen.getByText(/integrity guard/)).toBeInTheDocument();
    expect(screen.queryByText("blocked by a delivered test")).not.toBeInTheDocument();
  });

  it("passes the ticked tests to onDecide, and nothing when none are ticked", () => {
    const seen: string[][] = [];
    render(
      <GatePanel
        gate={gateWith({
          amendable: { paths: ["tests/a.py"], tests: ["tests/a.py::test_x", "tests/a.py::test_y"] },
        })}
        busy={false}
        onDecide={(_a, _f, authorized) => seen.push(authorized ?? [])}
      />,
    );
    // Nothing ticked ⇒ nothing authorized. An amendment must take a deliberate act.
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));
    expect(seen[0]).toEqual([]);

    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    fireEvent.click(boxes[0]);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));
    expect(seen[1]).toEqual(["tests/a.py::test_x"]); // ONLY the one ticked — not the file
  });
});


// --- computed outcomes: the gate states its own consequences (ADR-0082 §1, F61) ---------------
//
// The run that discarded ~1.1M tokens was shown a "Send back to revise" button whose only effect
// was to end the run and throw the notes away. The engine now says which answers exist and what
// each does; the panel must render exactly those and nothing else.

const _TERMINAL_OUTCOMES = [
  {
    id: "approve",
    label: "Approve anyway",
    consequence: "Delivers over 1 unresolved gate reason(s) — recorded on the receipt as an override.",
    effect: "approve",
    recommended: false,
    override: true,
  },
  {
    id: "end_run",
    label: "End the run without delivering",
    consequence:
      "Nothing is committed and your notes are NOT acted on — the revision budget is spent (8 of 8).",
    effect: "end_run",
    recommended: true,
    override: false,
  },
];

it("at the cap it offers no send-back, and says the notes are discarded", () => {
  renderGate(gateWith({ outcomes: _TERMINAL_OUTCOMES }));
  expect(screen.queryByRole("button", { name: /Send back/i })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /End the run without delivering/ })).toBeInTheDocument();
  expect(screen.getByText(/NOT acted on/)).toBeInTheDocument();
});

it("the notes box stops promising a revision that cannot happen", () => {
  // Caught on the FIRST live run of the F61 fix: the options were correct and the placeholder
  // underneath still read "required to send back to revise". Same defect class, one layer down.
  renderGate(gateWith({ outcomes: _TERMINAL_OUTCOMES }));
  expect(screen.queryByPlaceholderText(/send back to revise/i)).not.toBeInTheDocument();
  expect(screen.getByPlaceholderText(/no revision follows/i)).toBeInTheDocument();
});

it("keeps the send-back placeholder while a send-back is actually offered", () => {
  const withSendBack = [
    _TERMINAL_OUTCOMES[0],
    {
      ..._TERMINAL_OUTCOMES[1],
      id: "send_back",
      effect: "send_back",
      label: "Send it back to revise",
    },
  ];
  renderGate(gateWith({ outcomes: withSendBack }));
  expect(screen.getByPlaceholderText(/send back to revise/i)).toBeInTheDocument();
});

it("sends the option_id so a stale screen can be refused", () => {
  const seen: (string | undefined)[] = [];
  render(
    <GatePanel
      gate={gateWith({ outcomes: _TERMINAL_OUTCOMES })}
      busy={false}
      onDecide={(_a, _f, _t, optionId) => seen.push(optionId)}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /End the run without delivering/ }));
  expect(seen[0]).toBe("end_run");
});

it("maps each option to the right approve boolean", () => {
  const seen: boolean[] = [];
  render(
    <GatePanel
      gate={gateWith({ outcomes: _TERMINAL_OUTCOMES })}
      busy={false}
      onDecide={(approve) => seen.push(approve)}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /Approve anyway/ }));
  fireEvent.click(screen.getByRole("button", { name: /End the run without delivering/ }));
  expect(seen).toEqual([true, false]);
});

it("marks the recommended option and never recommends an override", () => {
  renderGate(gateWith({ outcomes: _TERMINAL_OUTCOMES }));
  const badges = screen.getAllByText("recommended");
  expect(badges).toHaveLength(1);
  // The badge sits on End-the-run, not on the override.
  expect(badges[0].closest("button")!.textContent).toContain("End the run");
});

it("a write gate does not borrow delivery verbs", () => {
  // No outcomes declared yet for write gates — the legacy branch must still be kind-correct.
  renderGate(gateWith({ action: "write_file", gate_decision: undefined }));
  expect(screen.getByRole("button", { name: /Allow this change/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Approve & deliver/ })).not.toBeInTheDocument();
});

/* The `amend_tests` option must not be clickable until it MEANS something.
 *
 * Red team 2026-08-21, executed: the button reads "Authorise amending tests/x.py" and its
 * consequence promises "the Proctor re-authors it and the run continues" — but the click carries no
 * authorization; the checkbox list above it does. With nothing ticked, `amendment_delta` returns
 * empty, the oracle conflict stands, and `supervise_node` ENDS the run. F61's exact shape (surface
 * disagreeing with the engine) reproduced inside ADR-0107's own consequence machinery. */

const AMENDABLE = {
  paths: ["tests/test_row.py"],
  tests: ["tests/test_row.py::test_a", "tests/test_row.py::test_b"],
  criterion: "rows are pipe-delimited",
};

const AMEND_OUTCOMES = [
  {
    id: "amend_tests",
    label: "Authorise amending tests/test_row.py::test_a",
    consequence: "The Proctor re-authors it coder-blind, once, and the run continues.",
    effect: "send_back",
    recommended: true,
    override: false,
  },
  {
    id: "stop_honestly",
    label: "Stop and record it honestly",
    consequence: "Ends the run without delivering.",
    effect: "end_run",
    recommended: false,
    override: false,
  },
];

describe("amend_tests cannot be clicked before it authorizes anything", () => {
  function renderAmend() {
    return render(
      <GatePanel
        gate={
          {
            action: "escalation",
            amendable: AMENDABLE,
            outcomes: AMEND_OUTCOMES,
          } as unknown as GatePayload
        }
        busy={false}
        onDecide={() => {}}
      />,
    );
  }

  it("is disabled while no test is ticked", () => {
    renderAmend();
    const btn = screen.getByRole("button", { name: /Authorise amending/ });
    expect(btn).toBeDisabled();
  });

  it("needs BOTH a ticked test and a note — the note is the amendment's recorded reason", () => {
    renderAmend();
    const btn = () => screen.getByRole("button", { name: /Authorise amending/ });

    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    expect(btn()).toBeDisabled(); // authorized, but the tester would get no reason

    fireEvent.change(screen.getByPlaceholderText(/Notes for the coder/), {
      target: { value: "the requirement changed to pipe-delimited" },
    });
    expect(btn()).not.toBeDisabled();
  });

  it("a note alone is not authorization", () => {
    renderAmend();
    fireEvent.change(screen.getByPlaceholderText(/Notes for the coder/), {
      target: { value: "go ahead" },
    });
    expect(screen.getByRole("button", { name: /Authorise amending/ })).toBeDisabled();
  });

  it("the ENDING option stays available throughout — stopping never needs authorization", () => {
    renderAmend();
    expect(screen.getByRole("button", { name: /Stop and record it honestly/ })).not.toBeDisabled();
  });
});
