import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Compass, RefreshCw, Send } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

import { api, type MapDimension, type MapSeverity, severityRank } from "../../api/client";
import type { PmPrefillState } from "../../lib/backlog";
import { CardHead } from "./bits";

/** Findings → the PM's desk, verbatim and provenanced. Quincy is the accountable seat for
 *  turning observations into scoped work; the operator still approves whatever it proposes.
 *  The digest is DATA handed to a chat draft the operator sends — never auto-submitted. */
function quincyDigest(dims: MapDimension[]): string {
  const lines: string[] = [
    "Recon flagged the following on the project map:",
    "",
  ];
  for (const d of dims) {
    if (d.status === "clean") continue;
    lines.push(`**${d.dimension}** — ${d.status}`);
    if (d.status === "unavailable" && d.unavailable_reason) lines.push(`- ${d.unavailable_reason}`);
    for (const o of d.observations.slice(0, 6)) {
      lines.push(`- [${o.provenance}] ${o.text}`);
    }
    lines.push("");
  }
  lines.push(
    "Which of these are worth fixing? Propose backlog items for the ones that are, and say why the rest can wait.",
  );
  return lines.join("\n");
}

type BadgeVariant = "default" | "secondary" | "outline" | "destructive";

/** A finding dimension is coloured by its WORST observation, so pure inventory (all `info`)
 *  reads neutral instead of alarming, and a real concern stands out. Clean/unavailable keep
 *  their honest tri-state treatment. */
function dimensionVariant(dim: MapDimension): BadgeVariant {
  if (dim.status === "clean") return "secondary";
  if (dim.status === "unavailable") return "outline"; // never rounded to clean (ADR-0047 §5)
  const worst = dim.observations.reduce((m, o) => Math.max(m, severityRank(o.severity)), 0);
  if (worst >= severityRank("high")) return "destructive"; // high / critical
  if (worst >= severityRank("medium")) return "default"; // amber
  if (worst >= severityRank("low")) return "outline"; // muted
  return "secondary"; // all info — neutral, not an alarm
}

/** A small severity dot for an elevated observation (`info` shows none). */
const SEVERITY_DOT: Record<Exclude<MapSeverity, "info">, string> = {
  low: "bg-muted-foreground/50",
  medium: "bg-primary",
  high: "bg-destructive",
  critical: "bg-destructive",
};

/** The durable, UNTRUSTED project map (#42/ADR-0047): recon's per-dimension tri-state with
 *  provenanced observations + honest freshness. Repo-derived DATA the operator reads to scope
 *  the project — never instruction, never a gate input. */
export function ProjectMapCard({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["map", projectId],
    queryFn: () => api.getProjectMap(projectId),
    // Poll while a recon sweep is in flight so the map fills in without a manual refresh.
    refetchInterval: (q) => (q.state.data?.running ? 2000 : false),
  });

  const recon = useMutation({
    mutationFn: () => api.triggerRecon(projectId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["map", projectId] }),
  });

  const dims = data?.dimensions ?? [];
  const stale = new Set(data?.stale ?? []);
  const running = Boolean(data?.running);
  const hasFindings = dims.some((d) => d.status !== "clean");

  function sendToQuincy() {
    const state: PmPrefillState = { pmPrefill: quincyDigest(dims) };
    navigate(`/projects/${projectId}/pm`, { state });
  }

  return (
    <Card size="sm">
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardHead icon={Compass}>Project map</CardHead>
        <div className="flex items-center gap-2">
        {hasFindings && (
          <Button size="sm" variant="outline" className="h-7" onClick={sendToQuincy}>
            <Send className="size-3.5" />
            Send to Quincy
          </Button>
        )}
        <Button
          size="sm"
          variant="outline"
          className="h-7"
          onClick={() => recon.mutate()}
          disabled={running || recon.isPending}
        >
          <RefreshCw className={`size-3.5 ${running ? "animate-spin" : ""}`} />
          {running ? "Reconning…" : "Re-run recon"}
        </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {data?.error && (
          <p role="alert" className="text-xs text-destructive">
            recon error: {data.error}
          </p>
        )}
        {isLoading ? (
          <p className="text-[13px] text-muted-foreground">Loading the map…</p>
        ) : dims.length === 0 ? (
          // One quiet line, not a built-out empty state — the header button IS the action.
          <p className="text-[13px] text-muted-foreground">
            No map yet — run recon to scan the repository.
          </p>
        ) : (
          /* Chip grid (owner cut, 2026-08-13): the map is a few LINES of tri-state chips
             until a dimension is dug into — each expandable chip reveals its observations.
             A dimension with nothing inside renders as a flat chip, not a dead disclosure. */
          <ul className="grid grid-cols-1 items-start gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
            {dims.map((d) => {
              const body: React.ReactNode[] = [];
              if (d.status === "unavailable" && d.unavailable_reason) {
                body.push(
                  <span key="why" className="text-xs leading-snug text-muted-foreground">
                    {d.unavailable_reason}
                  </span>,
                );
              }
              const summary = (
                <>
                  <span className="text-[13px] font-medium capitalize">{d.dimension}</span>
                  <Badge variant={dimensionVariant(d)} className="capitalize">
                    {d.status}
                  </Badge>
                  {stale.has(d.dimension) && (
                    <Badge variant="outline" className="text-[10px] text-primary">
                      stale
                    </Badge>
                  )}
                  {d.observations.length > 0 && (
                    <span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground/60">
                      {d.observations.length}
                    </span>
                  )}
                </>
              );
              const expandable = d.observations.length > 0 || body.length > 0;
              return (
                <li key={d.dimension} className="min-w-0">
                  {expandable ? (
                    <details className="rounded-md bg-muted/30">
                      <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-1.5 hover:bg-muted/50 [&::-webkit-details-marker]:hidden">
                        {summary}
                      </summary>
                      <div className="flex flex-col gap-1.5 px-3 pb-2.5 pt-0.5">
                        {body}
                        {d.observations.length > 0 && (
                          <ul className="flex flex-col gap-0.5">
                            {d.observations.slice(0, 6).map((o, i) => (
                              <li
                                key={i}
                                className="flex items-start gap-1.5 text-[12.5px] leading-relaxed text-foreground/85"
                              >
                                {o.severity && o.severity !== "info" && (
                                  <span
                                    className={`mt-1 size-1.5 shrink-0 rounded-full ${SEVERITY_DOT[o.severity]}`}
                                    aria-label={`${o.severity} severity`}
                                  />
                                )}
                                <span>
                                  <span className="mr-1 rounded bg-white/5 px-1 py-px font-mono text-[10px] text-muted-foreground">
                                    {o.provenance}
                                  </span>
                                  {o.text}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </details>
                  ) : (
                    <div className="flex items-center gap-2 rounded-md bg-muted/30 px-2.5 py-1.5">
                      {summary}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
