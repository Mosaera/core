/** A turn that did not complete must not read as an answer.
 *
 *  Two failures used to be indistinguishable from Quincy speaking: the server stored its apology
 *  as a `pm` row (so it arrived with his avatar and name), and the chat panel's role ternary sent
 *  anything that was not `pm` into the USER bubble — which would have rendered an engine failure
 *  as the operator's own words.
 *
 *  The copy rule is the other half, and it is the one with a measured history: a cause must never
 *  blame the operator for an engine or infrastructure limit. Only `empty` — where the model
 *  returned nothing and we cannot say why — may suggest rephrasing.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PmTurnFailure } from "@/components/pm/PmTurnFailure";
import { pmTurnFailure } from "@/lib/plain";

const CAUSES = ["model_failed", "budget_exhausted", "empty"] as const;

describe("the failure note", () => {
  it("shows the plain sentence and the raw token beside it", () => {
    render(<PmTurnFailure cause="model_failed" />);
    expect(screen.getByText(/couldn't be reached/)).toBeInTheDocument();
    expect(screen.getByText("model_failed")).toBeInTheDocument();
  });

  it("never renders as Quincy — no name, no avatar", () => {
    const { container } = render(<PmTurnFailure cause="model_failed" />);
    expect(screen.queryByText("Quincy")).not.toBeInTheDocument();
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });

  it("is a note, not an alert — it persists and must not re-announce itself", () => {
    render(<PmTurnFailure cause="empty" />);
    expect(screen.getByRole("note")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders an unknown cause readably rather than blank or broken", () => {
    // `parkCause`'s precedent: a token this build does not know still gets a sentence, with the
    // underscores unpicked, rather than an empty row.
    render(<PmTurnFailure cause="some_new_cause" />);
    expect(screen.getByText(/\(some new cause\)/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing was changed/)).toBeInTheDocument();
  });
});

describe("the copy never blames the operator for an engine failure", () => {
  it("offers rephrasing for `empty` only", () => {
    expect(pmTurnFailure("empty")).toMatch(/rephras/i);
    for (const cause of ["model_failed", "budget_exhausted"]) {
      const text = pmTurnFailure(cause);
      expect(text, `${cause} tells the operator to rephrase`).not.toMatch(/rephras/i);
      expect(text, `${cause} tells the operator to try again`).not.toMatch(/try again/i);
    }
  });

  it("names an infrastructure failure as one", () => {
    expect(pmTurnFailure("model_failed")).toMatch(/not a problem with what you asked/i);
  });

  it("points a budget exhaustion at the budget, not at the request", () => {
    expect(pmTurnFailure("budget_exhausted")).toMatch(/the request is not the problem/i);
  });

  it("gives every cause a DIFFERENT sentence", () => {
    const said = new Set(CAUSES.map(pmTurnFailure));
    expect(said.size).toBe(CAUSES.length);
  });

  it("says nothing at all when there is no cause", () => {
    expect(pmTurnFailure("")).toBe("");
  });
});
