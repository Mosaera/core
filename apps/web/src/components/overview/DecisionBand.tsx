import { X } from "lucide-react";

import { useQueryClient } from "@tanstack/react-query";

import type { Project } from "../../api/client";
import { acknowledge, canAcknowledge } from "../../lib/decisionAck";
import { useDecisions } from "../../hooks/useDecisions";
import { DecisionCard } from "./DecisionCard";
import { ConsoleLabel } from "./bits";

/** "Waiting on you" — the server-derived decisions (ADR-0105), on the page the operator opens
 *  first, mirrored on the header bell through the SAME query.
 *
 *  Blocking conditions come first and CANNOT be dismissed: `gate:{run_id}` is one id for a run
 *  that may park at several different gates, so an acknowledgment could silence a later question
 *  invisibly — an unrecorded suppression of an ask (ADR-0107). Standing advisories can be
 *  dismissed, keyed to the text the operator actually read, so a changed finding re-raises. */
export function DecisionBand({ project }: { project: Project }) {
  const qc = useQueryClient();
  const { blocking, standing, isLoading } = useDecisions(project.id);
  if (isLoading || (blocking.length === 0 && standing.length === 0)) return null;

  function dismiss(id: string) {
    const d = [...blocking, ...standing].find((x) => x.id === id);
    if (!d || !canAcknowledge(d)) return;
    acknowledge(project.id, d, Date.now());
    // Re-read from cache so the band updates without another GitLab-touching request.
    qc.invalidateQueries({ queryKey: ["decisions", project.id], refetchType: "none" });
    qc.setQueryData(["decisions", project.id], (prev: unknown) => prev);
  }

  return (
    <section aria-label="Waiting on you" className="flex flex-col gap-2">
      {blocking.length > 0 && <ConsoleLabel>Waiting on you</ConsoleLabel>}
      {blocking.map((d) => (
        <DecisionCard key={d.id} project={project} decision={d} />
      ))}
      {standing.length > 0 && (
        <>
          <ConsoleLabel className="mt-1">Standing</ConsoleLabel>
          {standing.map((d) => (
            <div key={d.id} className="relative">
              <DecisionCard project={project} decision={d} />
              <button
                type="button"
                aria-label={`Dismiss: ${d.title}`}
                onClick={() => dismiss(d.id)}
                className="absolute right-2 top-2 rounded border-0 bg-transparent p-1 text-muted-foreground/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              >
                <X className="size-3.5" />
              </button>
            </div>
          ))}
        </>
      )}
    </section>
  );
}
