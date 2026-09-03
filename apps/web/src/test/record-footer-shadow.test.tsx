import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { RunCost } from "../api/client";
import { RecordFooter } from "../components/runs/RecordFooter";

/** The receipt footer must not report "$0.00" for a run that would have cost real money.
 *
 * Live 2026-08-20: run 20260820-222037-95c397 spent 704,964 tokens with `usd: 0.0` and
 * `shadow_usd: 2.054476`, and the footer showed a flat "$0.00" — it never consulted
 * `shadow_usd`, while RunDetailPanel did. The imputed figure is the number an operator needs
 * BEFORE moving a role to a hosted model, so dropping it hides the whole point of the meter. */

function cost(over: Partial<RunCost> = {}): RunCost {
  return {
    input_tokens: 683342,
    output_tokens: 21622,
    total_tokens: 704964,
    usd: 0,
    shadow_usd: 2.054476,
    calls: 67,
    ...over,
  } as RunCost;
}

function wrap(c: RunCost) {
  return render(
    <MemoryRouter>
      <RecordFooter rid="20260820-222037-95c397" seal={null} cost={c} />
    </MemoryRouter>,
  );
}

describe("RecordFooter shadow spend", () => {
  it("shows the imputed on-box cost when nothing was billed", () => {
    wrap(cost());
    expect(screen.getByText(/~\$2\.0545 shadow/)).toBeTruthy();
  });

  it("still reports $0.00 as the REAL spend, so shadow is never read as a bill", () => {
    wrap(cost());
    expect(screen.getByText(/\$0\.00/)).toBeTruthy();
  });

  it("shows real spend and no shadow figure once a hosted model is billed", () => {
    wrap(cost({ usd: 1.25, shadow_usd: 0.5 }));
    expect(screen.getByText(/\$1\.2500/)).toBeTruthy();
    expect(screen.queryByText(/shadow/)).toBeNull();
  });

  it("omits the shadow segment entirely when there is no imputed cost", () => {
    wrap(cost({ shadow_usd: 0 }));
    expect(screen.queryByText(/shadow/)).toBeNull();
  });

  it("stamps the profiles the run STARTED with, beside its own numbers (ADR-0122)", () => {
    // The point of recording them: a finished run then reads as an observation about THIS run,
    // not as the general promise a profile label makes. A later settings change must not be able
    // to re-describe it, which is why the value comes from the run record and not from settings.
    render(
      <RecordFooter
        rid="r1"
        seal={null}
        profiles={{ effort_profile: "persistent", quality_profile: "strict" }}
      />,
    );
    expect(screen.getByText("effort")).toBeInTheDocument();
    expect(screen.getByText("persistent")).toBeInTheDocument();
    expect(screen.getByText("quality")).toBeInTheDocument();
    expect(screen.getByText("strict")).toBeInTheDocument();
  });
});
