/* Project-wide proof: what the DELIVERED work stands on, independence first.
 *
 * This replaced a radar of the latest SETTLED run (2026-08-22). On a real project the latest
 * settled run is usually a park where nothing was checked, so the page reported "not-checked"
 * three times over a project whose delivered work was fully checked — the flagship instrument
 * drawing "we know nothing" while 13 items had shipped. It was a run-level instrument on a
 * project page, fed by the thinnest data in the codebase.
 *
 * The derivation and its three counting rules live in `lib/proofAggregate.ts`.
 *
 * It renders as a LARGE spider chart (owner directive, 2026-08-23: it read as "something tossed to
 * the side"). The bars it briefly replaced were the right call when only three axes were
 * answerable — a three-spoke radar is a triangle whose area means nothing — but ADR-0109's
 * server-side aggregate answers six from the sealed receipts, so the shape carries information
 * again. The counts stay printed beside every axis: the chart is the summary, the numbers are the
 * truth. Independence leads the list beneath even though it reads zero — a governance product that
 * hides its own weakest number is a dashboard. */

import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";

import { api, type Project } from "../../api/client";
import type { ProofTone } from "../../lib/proofAggregate";
import { projectProof, type ProofAxis, proofTone } from "../../lib/proofAggregate";
import { ProjectProofRadar } from "./ProjectProofRadar";
import { Card, CardContent } from "../ui/card";
import { CardHead, ConsoleLabel } from "./bits";

/** One line per axis beneath the chart: what the axis MEANS. The COUNT is not repeated here — the
 *  chart prints every denominator beside its own spoke, and saying it twice on one card is the
 *  duplication this console spent an arc removing. Chart = the numbers, list = what they measure. */
/** Same bands as the chart, so the dot and the spoke can never disagree. */
const TONE_DOT: Record<ProofTone, string> = {
  unmeasured: "bg-muted-foreground/40",
  strong: "bg-success",
  fair: "bg-primary",
  weak: "bg-destructive",
};

function AxisNote({ axis }: { axis: ProofAxis }) {
  return (
    <li className="flex items-baseline gap-2 text-[12.5px]">
      <span
        aria-hidden
        className={cn(
          "mt-1.5 size-1.5 shrink-0 rounded-full",
          TONE_DOT[proofTone(axis)],
        )}
      />
      <span className="min-w-0 flex-1">
        <span className="font-medium">{axis.label}</span>
        <span className="text-muted-foreground"> — {axis.note}</span>
      </span>
    </li>
  );
}

export function ProofCard({ project }: { project: Project }) {
  // Receipt-backed axes (review / security / proof depth) exist only inside each run's sealed
  // receipt, so they are aggregated SERVER-side (ADR-0109) rather than by fetching one receipt per
  // delivered run. The client-side three stay as the fallback: if that read fails, the panel
  // degrades to what the run list can answer honestly rather than showing nothing.
  const { data: served } = useQuery({
    queryKey: ["project-proof", project.id],
    queryFn: () => api.projectProof(project.id),
    retry: false,
  });
  const local = projectProof(project.runs ?? [], project.backlog ?? []);
  const proof = served
    ? {
        delivered: served.delivered,
        axes: served.axes.map((a) => ({
          key: a.key as ProofAxis["key"],
          label: a.label,
          note: a.note,
          proven: a.proven,
          failed: a.failed,
          unknown: a.unknown,
          measured: a.measured,
        })),
      }
    : local;
  if (proof.delivered === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col gap-2">
          <CardHead icon={ShieldCheck}>Proof</CardHead>
          {/* Honest empty state: a sentence, never an empty shape implying a measurement. */}
          <p className="text-sm text-muted-foreground">
            Nothing has delivered yet — this fills in when the first item ships.
          </p>
        </CardContent>
      </Card>
    );
  }
  const independence = proof.axes.find((a) => a.key === "independence");
  if (!independence) return null;
  const rest = proof.axes.filter((a) => a.key !== "independence");
  return (
    <Card>
      <CardContent className="flex flex-col gap-3">
        <CardHead icon={ShieldCheck}>Proof</CardHead>
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          Across the <span className="text-foreground">{proof.delivered}</span> items that have
          delivered — one attempt each, the one that shipped, so remediated failures do not count
          against it.
        </p>
        <ProjectProofRadar axes={proof.axes} size={340} className="my-1" />
        <ul className="flex flex-col gap-1.5">
          {/* Independence leads: the weakest number, stated first, with its own denominator. */}
          <AxisNote axis={independence} />
          {rest.map((a) => (
            <AxisNote key={a.key} axis={a} />
          ))}
        </ul>
        <ConsoleLabel>
          measured on delivery ·{" "}
          <Link to={`/projects/${project.id}/runs`} className="text-primary hover:underline">
            runs →
          </Link>
        </ConsoleLabel>
      </CardContent>
    </Card>
  );
}
