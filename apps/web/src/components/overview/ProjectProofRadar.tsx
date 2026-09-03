/* The project's proof shape — the page's centerpiece (owner directive, 2026-08-23: it read as
 * "something tossed to the side").
 *
 * A DIFFERENT INSTRUMENT from `runs/ProofRadar`, deliberately. That one draws ONE run's tri-state
 * rings (proven / weak / not-checked). This draws the whole project: each axis is a COUNT over the
 * items that have delivered, so its radius is `proven / measured` — a measured proportion with a
 * visible denominator, never a synthesized quality score. Two axis models in one component is how
 * the rings drift, so they stay apart.
 *
 * Three honesty rules, carried from ADR-0109 and enforced in the geometry:
 *  - AN UNMEASURED AXIS IS NOT A ZERO. `measured === 0` means nothing was recorded; the polygon
 *    SKIPS that vertex and the spoke renders dashed. Drawing it at the centre would state a
 *    finding the receipts never made.
 *  - A MEASURED ZERO IS REAL and does sit at the centre — with a solid marker, so "0 of 13" and
 *    "not recorded" cannot be confused at a glance.
 *  - EVERY AXIS PRINTS ITS OWN DENOMINATOR next to its name. The shape is the summary; the counts
 *    are the truth. */

import { cn } from "@/lib/utils";

import type { ProofAxis, ProofTone } from "../../lib/proofAggregate";
import { proofTone } from "../../lib/proofAggregate";

/** Half-width of the widest label block, in SVG units — the gutter the labels need so nothing
 *  clips (the lesson from the per-run radar, whose left label rendered at x = -9.5 for months). */
const LABEL_HALF = 58;
const LABEL_GAP = 18;

function pt(i: number, n: number, r: number, cx: number, cy: number): [number, number] {
  const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

/** null = nothing recorded (skip the vertex); otherwise 0..1 of what was measured. */
/** Strength BANDS, not a binary. `proofTone` owns the thresholds; this owns only the paint.
 *  Previously any axis short of perfect was one colour, so 24 of 25 looked like 1 of 25 — and an
 *  axis that reads the same at 96% and 4% is one an operator stops reading (owner, 2026-08-24). */
const TONE_FILL: Record<ProofTone, string> = {
  unmeasured: "fill-muted-foreground/60",
  strong: "fill-success",
  fair: "fill-primary",
  weak: "fill-destructive",
};

function share(a: ProofAxis): number | null {
  return a.measured === 0 ? null : a.proven / a.measured;
}

export function ProjectProofRadar({
  axes,
  size = 340,
  className,
}: {
  axes: ProofAxis[];
  size?: number;
  className?: string;
}) {
  const cx = size / 2;
  const cy = size / 2;
  const R = size / 2 - LABEL_GAP - LABEL_HALF;
  const n = axes.length;
  if (n === 0 || R <= 10) return null;

  const shapePoints = axes
    .map((a, i) => {
      const s = share(a);
      return s === null ? null : pt(i, n, R * Math.max(s, 0.02), cx, cy);
    })
    .filter((p): p is [number, number] => p !== null)
    .map((p) => p.join(","))
    .join(" ");

  const summary = axes
    .map((a) => `${a.label}: ${a.measured === 0 ? "not recorded" : `${a.proven} of ${a.measured}`}`)
    .join("; ");

  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      width="100%"
      height="auto"
      role="img"
      aria-label={`Project proof — ${summary}`}
      className={cn("mx-auto block max-w-full", className)}
      style={{ maxWidth: size }}
    >
      {[1, 2, 3, 4].map((ring) => (
        <polygon
          key={ring}
          points={axes.map((_, i) => pt(i, n, (R * ring) / 4, cx, cy).join(",")).join(" ")}
          fill="none"
          className="stroke-border"
          strokeWidth={ring === 4 ? 1.25 : 0.75}
        />
      ))}

      {axes.map((a, i) => {
        const [ex, ey] = pt(i, n, R, cx, cy);
        const [lx, ly] = pt(i, n, R + LABEL_GAP, cx, cy);
        const s = share(a);
        const unmeasured = s === null;
        const zero = s === 0;
        const [mx, my] = pt(i, n, R * Math.max(s ?? 0, 0.02), cx, cy);
        // Anchor by hemisphere so labels grow away from the chart rather than over it.
        const anchor = Math.abs(lx - cx) < 4 ? "middle" : lx > cx ? "start" : "end";
        return (
          <g key={a.key}>
            <line
              x1={cx}
              y1={cy}
              x2={ex}
              y2={ey}
              className="stroke-border"
              strokeWidth={0.75}
              strokeDasharray={unmeasured ? "2 4" : undefined}
            />
            {!unmeasured && (
              <circle
                cx={mx}
                cy={my}
                r={zero ? 3.5 : 3}
                className={TONE_FILL[proofTone(a)]}
              />
            )}
            <text
              x={lx}
              y={ly - 2}
              textAnchor={anchor}
              className="fill-muted-foreground font-mono text-[9px] uppercase tracking-[0.12em]"
            >
              {a.label}
            </text>
            <text
              x={lx}
              y={ly + 10}
              textAnchor={anchor}
              className={cn("font-mono text-[10px] tabular-nums", TONE_FILL[proofTone(a)])}
            >
              {unmeasured ? "not recorded" : `${a.proven} of ${a.measured}`}
            </text>
          </g>
        );
      })}

      {shapePoints && (
        <polygon
          points={shapePoints}
          className="fill-success/15 stroke-success"
          strokeWidth={1.5}
        />
      )}
    </svg>
  );
}
