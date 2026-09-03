/* The deterministic edge router (#63): turns measured node positions + the
   derived EngineEdge list into SVG geometry. A send-back edge always renders
   the same way — exit the source's top port, rise into a reserved lane ABOVE
   the row (the space below belongs to the labels), run left with rounded
   orthogonal corners, drop into the target's top port, arrowhead down, count
   badge centered on the lane. One lane per return edge, stacked by span
   (narrowest closest to the row). Same run record → same picture. Pure; tested
   in engine-edge-router.test.ts. */

import type { AgentId, EdgeState, EngineEdge } from "../../../lib/engine";

export interface NodeBox {
  id: AgentId;
  /** Avatar center x/y and radius, in container coordinates. */
  cx: number;
  cy: number;
  r: number;
  /** Avatar top y. */
  top: number;
}

export interface ForwardGeom {
  from: AgentId;
  to: AgentId;
  state: EdgeState;
  x1: number;
  x2: number;
  y: number;
}

export interface BackGeom {
  from: AgentId;
  to: AgentId;
  state: EdgeState;
  path: string;
  /** Arrowhead (pointing down into the target's top port). */
  arrow: string;
  badge: { x: number; y: number; label: string };
}

export interface EdgeLayout {
  forward: ForwardGeom[];
  back: BackGeom[];
  /** Vertical space the lanes need above the avatar row. */
  laneHeight: number;
}

export const LANE_H = 32;
export const LANE_GAP = 22;
const CORNER = 9;
const PORT_GAP = 5; // gap between an avatar's edge and a wire's endpoint

export function routeEdges(nodes: NodeBox[], edges: EngineEdge[]): EdgeLayout {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const order = new Map(nodes.map((n, i) => [n.id, i]));
  const minTop = nodes.length > 0 ? Math.min(...nodes.map((n) => n.top)) : 0;

  const forward: ForwardGeom[] = [];
  for (const e of edges) {
    if (e.kind !== "forward") continue;
    const a = byId.get(e.from);
    const b = byId.get(e.to);
    if (!a || !b) continue;
    forward.push({
      from: e.from,
      to: e.to,
      state: e.state,
      x1: a.cx + a.r + PORT_GAP,
      x2: b.cx - b.r - PORT_GAP,
      y: a.cy,
    });
  }

  // Lanes: narrowest span sits closest to the row — deterministic, always.
  const backs = edges
    .filter((e) => e.kind === "back")
    .map((e) => ({ e, span: Math.abs((order.get(e.from) ?? 0) - (order.get(e.to) ?? 0)) }))
    .sort((a, b) => a.span - b.span || a.e.from.localeCompare(b.e.from));

  const back: BackGeom[] = backs.map(({ e }, lane) => {
    const f = byId.get(e.from)!;
    const t = byId.get(e.to)!;
    const y0f = f.top - PORT_GAP;
    const y0t = t.top - PORT_GAP;
    const laneY = minTop - LANE_GAP - lane * LANE_H;
    const R = CORNER;
    // Right-to-left is the send-back direction; mirror when the target sits right.
    const leftward = t.cx < f.cx;
    const path = leftward
      ? `M${f.cx} ${y0f} V${laneY + R} q0 -${R} -${R} -${R} H${t.cx + R} q-${R} 0 -${R} ${R} V${y0t - 7}`
      : `M${f.cx} ${y0f} V${laneY + R} q0 -${R} ${R} -${R} H${t.cx - R} q${R} 0 ${R} ${R} V${y0t - 7}`;
    return {
      from: e.from,
      to: e.to,
      state: e.state,
      path,
      arrow: `M${t.cx} ${y0t - 1} l-4 -7 h8 z`,
      badge: {
        x: (f.cx + t.cx) / 2,
        y: laneY,
        label: e.label ?? (e.count != null ? `×${e.count}` : ""),
      },
    };
  });

  return {
    forward,
    back,
    laneHeight: backs.length > 0 ? LANE_GAP + backs.length * LANE_H : 0,
  };
}
