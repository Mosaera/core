import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentId, AgentState, EngineEdge } from "../lib/engine";
import { EngineBand } from "../components/runs/engine/EngineBand";

/* jsdom has no layout: every getBoundingClientRect is 0×0, so the band would
   measure nothing and draw nothing. Stub a plausible layout — the avatar spans
   carry data-node, everything else answers as the row. */
function stubLayout(order: AgentId[]) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
    this: HTMLElement,
  ) {
    const id = this.getAttribute("data-node") as AgentId | null;
    if (id) {
      const i = Math.max(0, order.indexOf(id));
      return { left: 20 + i * 150, top: 17, width: 66, height: 66, right: 0, bottom: 0, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
    }
    return { left: 0, top: 0, width: 1000, height: 120, right: 0, bottom: 0, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
  });
}

const agent = (id: AgentId, status: AgentState["status"], caption = "x"): AgentState => ({
  id,
  name: id.charAt(0).toUpperCase() + id.slice(1),
  role: "r",
  status,
  caption,
});

const LIVE_ROSTER: AgentState[] = [
  agent("quincy", "done", "planned · 02:18"),
  agent("forge", "done", "3 builds"),
  agent("vera", "done", "green on run 3"),
  agent("rook", "current", "reviewing…"),
  agent("you", "pending", "gate not reached"),
  agent("drift", "pending", "nothing delivered"),
];
const ORDER = LIVE_ROSTER.map((a) => a.id);

const EDGES: EngineEdge[] = [
  { from: "quincy", to: "forge", kind: "forward", state: "traversed" },
  { from: "forge", to: "vera", kind: "forward", state: "traversed" },
  { from: "vera", to: "rook", kind: "forward", state: "current" },
  { from: "rook", to: "you", kind: "forward", state: "unreached" },
  { from: "you", to: "drift", kind: "forward", state: "unreached" },
  { from: "vera", to: "forge", kind: "back", state: "traversed", count: 2, label: "checks failed ×2" },
];

beforeEach(() => {
  vi.restoreAllMocks();
  stubLayout(ORDER);
});

describe("EngineBand — the run drawn from its own events", () => {
  it("renders every agent with its status and honest caption", () => {
    render(<EngineBand agents={LIVE_ROSTER} edges={EDGES} selected="rook" onSelect={() => {}} live />);
    expect(screen.getByText("Quincy")).toBeInTheDocument();
    expect(screen.getByText("reviewing…")).toBeInTheDocument();
    expect(screen.getByText("nothing delivered")).toBeInTheDocument();
    expect(document.querySelector('[data-agent="rook"]')).toHaveAttribute("data-status", "current");
    expect(document.querySelector('[data-agent="drift"]')).toHaveAttribute("data-status", "pending");
  });

  it("only the current agent shows a live presence dot", () => {
    render(<EngineBand agents={LIVE_ROSTER} edges={EDGES} selected="rook" onSelect={() => {}} live />);
    expect(document.querySelectorAll("[data-live-dot]")).toHaveLength(1);
  });

  it("exactly one edge animates, and only while live", () => {
    const { rerender } = render(
      <EngineBand agents={LIVE_ROSTER} edges={EDGES} selected="rook" onSelect={() => {}} live />,
    );
    // jsdom renders SMIL inert — presence is the assertion, never motion.
    expect(document.querySelectorAll("animateMotion")).toHaveLength(1);
    expect(document.querySelector('[data-edge="vera->rook"]')).toHaveAttribute("data-state", "current");

    const sealed = LIVE_ROSTER.map((a) => agent(a.id, "done", a.caption));
    const quiet: EngineEdge[] = EDGES.map((e) => ({ ...e, state: "traversed" }));
    rerender(<EngineBand agents={sealed} edges={quiet} selected="you" onSelect={() => {}} />);
    expect(document.querySelectorAll("animateMotion")).toHaveLength(0);
    expect(document.querySelectorAll("[data-live-dot]")).toHaveLength(0);
  });

  it("a send-back lane renders only when that loop actually ran, with its count", () => {
    const { rerender } = render(
      <EngineBand agents={LIVE_ROSTER} edges={EDGES} selected="rook" onSelect={() => {}} live />,
    );
    expect(screen.getByText("checks failed ×2")).toBeInTheDocument();
    expect(document.querySelector('[data-edge="vera->forge"]')).toBeInTheDocument();

    const clean = EDGES.filter((e) => e.kind === "forward");
    rerender(<EngineBand agents={LIVE_ROSTER} edges={clean} selected="rook" onSelect={() => {}} live />);
    expect(screen.queryByText("checks failed ×2")).not.toBeInTheDocument();
    expect(document.querySelector('[data-edge="vera->forge"]')).not.toBeInTheDocument();
  });

  it("a run that died on a loop draws that lane red, not amber and not quiet", () => {
    const dead: EngineEdge[] = [
      ...EDGES.filter((e) => e.kind === "forward").map((e) => ({ ...e, state: "traversed" as const })),
      { from: "vera", to: "forge", kind: "back", state: "dead", count: 4, label: "checks failed ×4 — stopped here" },
    ];
    render(<EngineBand agents={LIVE_ROSTER} edges={dead} selected="forge" onSelect={() => {}} />);
    expect(document.querySelector('[data-edge="vera->forge"]')).toHaveAttribute("data-state", "dead");
    expect(screen.getByText("checks failed ×4 — stopped here")).toBeInTheDocument();
    expect(document.querySelectorAll("animateMotion")).toHaveLength(0);
  });

  it("clicking an agent selects it", () => {
    const onSelect = vi.fn();
    render(<EngineBand agents={LIVE_ROSTER} edges={EDGES} selected="rook" onSelect={onSelect} live />);
    fireEvent.click(screen.getByText("Vera"));
    expect(onSelect).toHaveBeenCalledWith("vera");
  });
});
