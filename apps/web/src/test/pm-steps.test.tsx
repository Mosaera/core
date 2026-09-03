/** Watching Quincy work, and the record he leaves behind.
 *
 *  A turn with lookups is several model calls, and several calls with a blank screen reads as a
 *  hang. These pin the two halves of the fix: the live line says WHAT he is doing while he does
 *  it, and the finished reply keeps a quiet record of what he checked.
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PmStepsSummary, PmWorking } from "@/components/pm/PmSteps";
import { createSseParser } from "@/lib/sse";
import { pmStep, pmStepsSummary } from "@/lib/plain";

const LOOKUP = { kind: "tool", tool: "project_history", arg: "failures" };

describe("the live status line", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("says what he is checking, not merely that he is busy", () => {
    render(<PmWorking steps={[LOOKUP]} prose={[]} startedAt={Date.now()} />);
    expect(screen.getByRole("status").textContent).toContain("Checking how this project fails");
  });

  it("says Thinking before there is anything to name", () => {
    render(<PmWorking steps={[]} prose={[]} startedAt={Date.now()} />);
    expect(screen.getByRole("status").textContent).toContain("Thinking");
  });

  it("ticks the elapsed seconds while he works", () => {
    const started = Date.now();
    const { container } = render(<PmWorking steps={[LOOKUP]} prose={[]} startedAt={started} />);
    // `act` so React flushes the interval's state update — the `total-elapsed` precedent.
    act(() => void vi.advanceTimersByTime(11_000));
    expect(container.textContent).toContain("11s");
  });

  it("shows what he said on the way, before the answer exists", () => {
    render(
      <PmWorking steps={[LOOKUP]} prose={["Let me check the history."]} startedAt={Date.now()} />,
    );
    expect(screen.getByText("Let me check the history.")).toBeInTheDocument();
  });

  it("announces only the current step, never the ticking clock", () => {
    // A live region containing a number that changes every second is unusable with a screen
    // reader; the clock is reassurance, not information.
    const { container } = render(
      <PmWorking steps={[LOOKUP]} prose={[]} startedAt={Date.now()} />,
    );
    const live = container.querySelectorAll("[aria-live]");
    expect(live).toHaveLength(1);
    expect(live[0].textContent).not.toMatch(/\d+s/);
  });
});

describe("the record under a finished reply", () => {
  it("summarises how many things he checked", () => {
    render(<PmStepsSummary steps={[LOOKUP, { ...LOOKUP, arg: "open_work" }]} seconds={11} />);
    expect(screen.getByText("checked 2 things · 11s")).toBeInTheDocument();
  });

  it("stays collapsed until asked", () => {
    const { container } = render(<PmStepsSummary steps={[LOOKUP]} />);
    // A couple of lookups per turn, expanded, would push the conversation off the screen.
    expect(container.querySelector("details")?.open).toBe(false);
  });

  it("lists the same words the live line used", () => {
    render(<PmStepsSummary steps={[LOOKUP]} />);
    expect(screen.getByText("Checking how this project fails")).toBeInTheDocument();
  });

  it("renders nothing at all when he looked nothing up", () => {
    const { container } = render(<PmStepsSummary steps={[]} />);
    expect(container.querySelector("details")).toBeNull();
  });

  it("says 1 thing, not 1 things", () => {
    expect(pmStepsSummary(1, 3)).toBe("checked 1 thing · 3s");
  });
});

describe("the step wording", () => {
  it("covers every question the tool accepts", () => {
    for (const q of ["open_work", "failures", "item_history", "criteria_failed", "orphaned"]) {
      expect(pmStep("project_history", q)).toMatch(/^Checking|^Reading/);
    }
  });

  it("degrades readably on a question this build does not know", () => {
    expect(pmStep("project_history", "something_new")).toContain("records");
  });
});

describe("the frame parser", () => {
  it("reassembles a frame split across chunks", () => {
    // The case that only shows up when the reply is long, i.e. exactly when it matters.
    const parse = createSseParser();
    expect(parse('event: step\ndata: {"kind":"proj')).toEqual([]);
    expect(parse('ect_history","detail":"failures"}\n\n')).toEqual([
      { event: "step", data: { kind: "project_history", detail: "failures" } },
    ]);
  });

  it("ignores a heartbeat comment", () => {
    const parse = createSseParser();
    expect(parse(": ping\n\n")).toEqual([]);
  });

  it("holds back a partial trailing frame", () => {
    const parse = createSseParser();
    expect(parse('event: done\ndata: {"reply":"hi"}')).toEqual([]);
  });

  it("drops a payload it cannot read rather than throwing", () => {
    // One malformed frame must not end a turn that is otherwise going fine.
    const parse = createSseParser();
    expect(parse("event: step\ndata: {not json}\n\n")).toEqual([]);
  });
});

describe("the knob has a control", () => {
  it("offers the ledger-tool toggle in the Planner section", async () => {
    // The gap this test exists for: the knob was settable by env var and persistable through the
    // settings API, but nothing in the browser could turn it on — so the feature shipped
    // unreachable. A backend knob with no control is a knob nobody flips.
    const { GROUPS } = await import("@/components/settings/AdvancedSettings");
    const planner = GROUPS.find((g) => g.title === "Planner (Quincy)");
    const fields = planner?.fields.map((f) => f.field) ?? [];
    expect(fields).toContain("pm_chat_tools");
  });

  it("names the knob exactly as the server does", async () => {
    // The form posts `field` straight through, so a typo here is a silent no-op: the toggle
    // moves, the setting does not.
    const { GROUPS } = await import("@/components/settings/AdvancedSettings");
    const all = GROUPS.flatMap((g) => g.fields.map((f) => f.field));
    expect(all.filter((f) => f === "pm_chat_tools")).toHaveLength(1);
  });
});
