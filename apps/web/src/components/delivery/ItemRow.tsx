import { ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { ItemMrRow } from "../../lib/delivery";
import { severityBadge } from "../StatusBadge";

/** One backlog item's delivery row on the Delivery page: its MR state, the link, and — when the
 *  MR is stuck because its target branch no longer exists — the reason and the repair. Extracted
 *  from DeliveryWorkspace when that file reached the 500-line ceiling; purely presentational, so
 *  every mutation stays with the workspace that owns the queries. */
export const MR_STATE_BADGE: Record<string, { label: string; tone: string }> = {
  merged: { label: "merged", tone: "green" },
  opened: { label: "MR open", tone: "amber" },
  closed: { label: "MR closed", tone: "neutral" },
};

export function ItemRow({
  row,
  busy,
  stuckOn,
  onOpen,
  onRetarget,
  onMrState,
  onMerge,
}: {
  row: ItemMrRow;
  busy: boolean;
  /** The MR's target branch, when it no longer exists — the MR cannot merge until repointed. */
  stuckOn?: string;
  /** Opens the compose sheet. Absent when this project's source has no forge to open a
   *  request on (ADR-0112) — same rule as `onMerge`: a control that cannot succeed is
   *  missing, not present-and-broken. */
  onOpen?: (id: number) => void;
  onRetarget: (id: number) => void;
  onMrState: (id: number, action: "close" | "reopen") => void;
  /** Opens the merge confirmation. Absent when the caller cannot merge (no api token), so the
   *  control is missing rather than present-and-broken. */
  onMerge?: (id: number) => void;
}) {
  const badge = MR_STATE_BADGE[row.mrState];
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border/40 py-2.5 first:border-t-0">
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium">
          #{row.id} · {row.title}
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 font-mono text-[10.5px] text-muted-foreground">
          <span>{row.status.replace(/_/g, " ")}</span>
          {row.branch && <span>{row.branch}</span>}
        </span>
        {stuckOn && (
          <span className="mt-1 block text-[11.5px] leading-relaxed text-amber-600 dark:text-amber-400">
            Stuck: this MR targets <span className="font-mono">{stuckOn}</span>, which no longer
            exists — GitLab can&rsquo;t merge it until it points somewhere real.
          </span>
        )}
      </span>
      {badge && (
        <Badge className={cn("font-mono text-[10px] uppercase", severityBadge(badge.tone))}>
          {badge.label}
        </Badge>
      )}
      {row.mrUrl && (
        <Button
          size="sm"
          variant="ghost"
          className="text-muted-foreground"
          nativeButton={false}
          render={<a href={row.mrUrl} target="_blank" rel="noreferrer" />}
        >
          <ExternalLink data-icon="inline-start" />
          View MR
        </Button>
      )}
      {stuckOn && (
        <Button size="sm" variant="outline" disabled={busy} onClick={() => onRetarget(row.id)}>
          Retarget
        </Button>
      )}
      {/* The other half of the lifecycle: an obsolete MR can be ended, and a close undone.
          Offered only where GitLab would accept it — a merged MR has no lifecycle left. */}
      {row.mrState === "opened" && (
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => onMrState(row.id, "close")}
        >
          Close MR
        </Button>
      )}
      {/* The last step of delivery, and the only one that changes the target branch of a real
          repository. Offered only on an OPEN MR — GitLab has nothing to merge otherwise — and the
          readiness verdict is read when the confirmation opens, never from this row: a row is as
          old as the last poll, and the operator is about to act on the MR as it is NOW. */}
      {row.mrState === "opened" && onMerge && (
        <Button size="sm" disabled={busy} onClick={() => onMerge(row.id)}>
          Merge
        </Button>
      )}
      {row.mrState === "closed" && (
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => onMrState(row.id, "reopen")}
        >
          Reopen MR
        </Button>
      )}
      {row.canOpen && onOpen && (
        <Button size="sm" disabled={busy} onClick={() => onOpen(row.id)}>
          {busy ? "Opening…" : "Open MR"}
        </Button>
      )}
    </li>
  );
}
