import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunDetail } from "../api/client";
import { CapabilityLimitNote } from "../components/runs/evidence";

function detailWith(reason: string | null): RunDetail {
  const decisions = reason ? [{ kind: "capability_limit", content: reason, created_at: null }] : [];
  return { decisions } as unknown as RunDetail;
}

describe("CapabilityLimitNote", () => {
  it("shows the honest capability reason when present", () => {
    render(
      <CapabilityLimitNote
        detail={detailWith(
          "Stopped — no progress: validation failed the same way 3 times in a row.",
        )}
      />,
    );
    expect(screen.getByText("Couldn't complete this task")).toBeInTheDocument();
    expect(screen.getByText(/no progress/)).toBeInTheDocument();
  });

  it("renders nothing when the run did not stall", () => {
    const { container } = render(<CapabilityLimitNote detail={detailWith(null)} />);
    expect(container.firstChild).toBeNull();
  });
});
