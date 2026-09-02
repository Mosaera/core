import type { BacklogItem } from "../../api/client";
import type { ItemGroup } from "../../lib/itemRuns";
import { CommitRow } from "./CommitRow";

/** One backlog item's changes: the latest attempt as the row, earlier attempts collapsed
 *  (redundancy audit 2026-08-22, owner decision). The Changes page used to list every attempt
 *  flat, so one stuck item filled eight near-identical rows; the Runs page already consolidates
 *  this way, and a "row" now means the same thing on both pages. Nothing leaves the record —
 *  every prior attempt is one disclosure away, in order. */
export function ItemChangeGroup({ group, backlog }: { group: ItemGroup; backlog: BacklogItem[] }) {
  const priors = group.attempts.filter((r) => r.id !== group.latest.id);
  return (
    <div className="border-b border-border/50 last:border-b-0">
      <CommitRow run={group.latest} backlog={backlog} />
      {priors.length > 0 && (
        <details className="group/attempts pb-2 pl-8 pr-1">
          <summary className="flex w-fit cursor-pointer list-none items-center gap-2 rounded px-1 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/70 hover:text-foreground [&::-webkit-details-marker]:hidden">
            attempt {group.attempts.length} of {group.attempts.length} · {priors.length} earlier
            <span className="transition-transform group-open/attempts:rotate-180">▾</span>
          </summary>
          <div className="flex flex-col">
            {priors.map((run, i) => (
              <CommitRow
                key={run.id}
                run={run}
                backlog={backlog}
                attemptLabel={`attempt ${priors.length - i}`}
              />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
