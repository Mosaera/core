/* The proof radar — discrete rings, hand-rolled SVG (house precedent: engine/EngineBand.tsx;
 * no chart library in this codebase, deliberately).
 *
 * Honesty rules, enforced in geometry:
 *  - three rings only (not-checked / weak / proven) — no decimals, no interpolation;
 *  - an axis the source cannot answer (value: null) renders a DASHED spoke and the value polygon
 *    SKIPS that vertex — never ring-0, which would read as a real "not-checked";
 *  - a breach renders a destructive marker on the spoke: "failed" never masquerades as
 *    "not-checked";
 *  - ghosts are prior runs' literal shapes at low opacity — never an average.
 * The SVG is presentation; every axis fact also exists as text (the per-axis notes list rendered
 * by VerdictCard), which is what the ADR-0082 summary rule reads. */

import type { AxisValue } from "../../lib/radar";

const RING: Record<string, number> = { "not-checked": 1, weak: 2, proven: 3 };

/** Half the width of the widest axis label at 10px mono ("proof depth" ≈ 62px). The side labels
 *  are centre-anchored, so this much must exist between the label centre and the viewBox edge. */
const LABEL_HALF_MAX = 32;

function pt(i: number, n: number, r: number, cx: number, cy: number): [number, number] {
  const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

function shapePoints(axes: AxisValue[], R: number, cx: number, cy: number): string {
  return axes
    .map((a, i) => (a.value ? pt(i, axes.length, (R * RING[a.value]) / 3, cx, cy) : null))
    .filter((p): p is [number, number] => p !== null)
    .map((p) => p.join(","))
    .join(" ");
}

export function ProofRadar({
  axes,
  ghosts = [],
  size = 220,
}: {
  axes: AxisValue[];
  /** Prior shapes (same axis order), rendered faint BEHIND the current shape. */
  ghosts?: AxisValue[][];
  size?: number;
}) {
  const cx = size / 2;
  const cy = size / 2 + 4;
  // Label gutter, not just tick clearance. Labels are centred on `R + LABEL_GAP`, so the widest
  // side label must still fit inside the viewBox: at 196px the old `size/2 - 34` put "integrity"
  // (55px wide) at x = -9.5 and the browser clipped it to "ITEGRI" on the overview; run pages lost
  // the "P" of "proof depth". Shrinking R rather than growing the viewBox keeps every mount's
  // layout footprint unchanged (redundancy/clarity audit 2026-08-22).
  const LABEL_GAP = 16;
  // Exactly enough gutter, not more: the label centre lands at `size/2 - LABEL_HALF_MAX`, so the
  // widest label ends flush with the edge. Subtracting the old 34 as WELL as the gutter shrank the
  // 168px compact mount to an 18px plot — caught by the geometry pin, which is why it exists.
  const R = size / 2 - LABEL_GAP - LABEL_HALF_MAX;
  const n = axes.length;
  const label = axes
    .map((a) => `${a.label}: ${a.value ?? "not recorded"}${a.breach ? " (breach)" : ""}`)
    .join("; ");
  return (
    <svg
      viewBox={`0 0 ${size} ${size + 8}`}
      width={size}
      height={size + 8}
      role="img"
      aria-label={`Proof radar — ${label}`}
      className="shrink-0"
    >
      {[1, 2, 3].map((ring) => (
        <polygon
          key={ring}
          points={axes.map((_, i) => pt(i, n, (R * ring) / 3, cx, cy).join(",")).join(" ")}
          fill="none"
          className="stroke-border"
          strokeWidth={1}
        />
      ))}
      {axes.map((a, i) => {
        const [x, y] = pt(i, n, R, cx, cy);
        const [lx, ly] = pt(i, n, R + LABEL_GAP, cx, cy);
        return (
          <g key={a.axis}>
            <line
              x1={cx}
              y1={cy}
              x2={x}
              y2={y}
              className="stroke-border"
              strokeDasharray={a.value === null ? "2 3" : undefined}
            />
            <text
              x={lx}
              y={ly + 3}
              textAnchor="middle"
              className={`font-mono text-[9px] uppercase tracking-[0.08em] ${
                a.breach ? "fill-destructive" : "fill-muted-foreground"
              }`}
            >
              {a.label}
            </text>
          </g>
        );
      })}
      {ghosts.map((g, gi) => (
        <polygon
          key={gi}
          points={shapePoints(g, R, cx, cy)}
          fill="none"
          className="stroke-muted-foreground"
          strokeWidth={1}
          opacity={0.22}
        />
      ))}
      <polygon
        points={shapePoints(axes, R, cx, cy)}
        className="fill-primary/20 stroke-primary"
        strokeWidth={1.5}
      />
      {axes.map((a, i) => {
        if (!a.breach) return null;
        const r = a.value ? (R * RING[a.value]) / 3 : R;
        const [x, y] = pt(i, n, r, cx, cy);
        return <circle key={a.axis} cx={x} cy={y} r={3.5} className="fill-destructive" />;
      })}
    </svg>
  );
}
