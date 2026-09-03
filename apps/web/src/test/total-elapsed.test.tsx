import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TotalElapsed } from "../components/runs/TotalElapsed";

/** The clock used to tick `Date.now() - startedAt` unconditionally, so a run parked awaiting a
 *  decision kept counting — reporting the OPERATOR's deliberation as run time. Observed live
 *  2026-08-20 on a run parked at a write gate. */
describe("TotalElapsed", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const startedAt = () => Math.floor(Date.now() / 1000);

  it("counts while the run is working", () => {
    render(<TotalElapsed startedAt={startedAt()} paused={false} />);
    act(() => void vi.advanceTimersByTime(5000));
    // textContent, not a text matcher: the label is split across JSX nodes.
    expect(screen.getByTitle("Working time").textContent).toContain("0m 5s");
  });

  it("STOPS while the run waits on you, and says it is paused", () => {
    const { rerender } = render(<TotalElapsed startedAt={startedAt()} paused={false} />);
    act(() => void vi.advanceTimersByTime(3000));

    rerender(<TotalElapsed startedAt={startedAt() - 3} paused={true} />);
    const atPause = screen.getByTitle(/stopped while the run waits/i).textContent;
    act(() => void vi.advanceTimersByTime(60000)); // a minute of the operator thinking

    expect(screen.getByTitle(/stopped while the run waits/i).textContent).toBe(atPause);
    expect(atPause).toContain("paused");
  });

  it("resumes without back-filling the wait", () => {
    const started = startedAt();
    const { rerender } = render(<TotalElapsed startedAt={started} paused={false} />);
    act(() => void vi.advanceTimersByTime(2000));

    rerender(<TotalElapsed startedAt={started} paused={true} />);
    act(() => void vi.advanceTimersByTime(120000)); // two minutes parked
    rerender(<TotalElapsed startedAt={started} paused={false} />);
    act(() => void vi.advanceTimersByTime(1000));

    // ~3s of work, not the 2m 3s of wall clock — the whole point.
    expect(screen.getByTitle("Working time").textContent).toMatch(/0m [23]s/);
  });
});
