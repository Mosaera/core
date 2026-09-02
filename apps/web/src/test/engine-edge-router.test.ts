import { describe, expect, it } from "vitest";

import type { AgentId, EngineEdge } from "../lib/engine";
import { LANE_GAP, LANE_H, routeEdges, type NodeBox } from "../components/runs/engine/edgeRouter";

const ROSTER: AgentId[] = ["quincy", "forge", "vera", "rook", "you", "drift"];
const boxes = (): NodeBox[] =>
  ROSTER.map((id, i) => ({ id, cx: 60 + i * 150, cy: 50, r: 33, top: 17 }));

const fwd = (from: AgentId, to: AgentId, state: EngineEdge["state"] = "traversed"): EngineEdge => ({
  from,
  to,
  kind: "forward",
  state,
});
const back = (from: AgentId, count: number, label: string): EngineEdge => ({
  from,
  to: "forge",
  kind: "back",
  state: "traversed",
  count,
  label,
});

describe("routeEdges — forward geometry", () => {
  it("wires join avatar side ports on the centerline", () => {
    const layout = routeEdges(boxes(), [fwd("quincy", "forge")]);
    expect(layout.forward).toEqual([
      { from: "quincy", to: "forge", state: "traversed", x1: 98, x2: 172, y: 50 },
    ]);
  });

  it("edges whose endpoints are not on the band are dropped, never guessed", () => {
    const layout = routeEdges(boxes(), [fwd("quincy", "proctor")]);
    expect(layout.forward).toHaveLength(0);
  });
});

describe("routeEdges — send-back lanes are deterministic", () => {
  it("one lane per return edge, stacked by span: narrowest closest to the row", () => {
    const layout = routeEdges(boxes(), [
      back("rook", 1, "changes requested ×1"), // span 2 — declared FIRST
      back("vera", 2, "checks failed ×2"), // span 1 — must still win the near lane
    ]);
    const [near, far] = layout.back;
    expect(near.from).toBe("vera");
    expect(far.from).toBe("rook");
    // Lane 0 sits closer to the row (larger y) than lane 1.
    expect(near.badge.y).toBeGreaterThan(far.badge.y);
    expect(near.badge.y).toBe(17 - LANE_GAP);
    expect(far.badge.y).toBe(17 - LANE_GAP - LANE_H);
  });

  it("declaration order never changes the picture — the same run renders identically", () => {
    const a = routeEdges(boxes(), [back("vera", 2, "checks failed ×2"), back("rook", 1, "x")]);
    const b = routeEdges(boxes(), [back("rook", 1, "x"), back("vera", 2, "checks failed ×2")]);
    expect(a).toEqual(b);
  });

  it("lanes route ABOVE the row and drop into the target's top port, arrow pointing down", () => {
    const layout = routeEdges(boxes(), [back("vera", 2, "checks failed ×2")]);
    const lane = layout.back[0];
    expect(lane.path).toMatch(/^M360 12 V/); // exits Vera's top port
    expect(lane.path).toContain("H219"); // runs left toward Forge
    expect(lane.arrow).toBe("M210 11 l-4 -7 h8 z"); // arrowhead into Forge's top
    expect(lane.badge).toMatchObject({ x: 285, label: "checks failed ×2" });
  });

  it("a rightward return (You → Quincy is leftward; reversed input mirrors) still closes the path", () => {
    const layout = routeEdges(boxes(), [
      { from: "quincy", to: "drift", kind: "back", state: "traversed", count: 1, label: "×1" },
    ]);
    expect(layout.back[0].path).toContain("q0 -9 9 -9"); // mirrored corner
  });

  it("no loops → no reserved space above the row", () => {
    expect(routeEdges(boxes(), [fwd("quincy", "forge")]).laneHeight).toBe(0);
    expect(routeEdges(boxes(), [back("vera", 1, "x")]).laneHeight).toBe(LANE_GAP + LANE_H);
  });
});
