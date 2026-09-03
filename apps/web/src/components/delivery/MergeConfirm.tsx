import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { api } from "../../api/client";
import { mergeability } from "../../lib/delivery";
import { providerNouns, type DeliveryProvider } from "../../lib/providerNouns";

/** The confirmation for the one action in this product that changes a real repository's target
 *  branch (ADR-0102 amendment).
 *
 *  **The verdict is read when this opens, not taken from the row.** A row is as old as the last
 *  poll; the operator is about to act on the merge request as it is NOW. Same rule ADR-0108 applies
 *  to gate evidence, on the one action that cannot be undone from here.
 *
 *  **It offers nothing it cannot justify.** A plain merge appears only when GitLab says
 *  `mergeable`; a running pipeline offers GitLab's own merge-when-it-passes instead; everything
 *  else — conflicts, a red pipeline, an unreadable answer — names itself and offers no merge at
 *  all. An unrecognised or missing status reads as not-ready (`lib/delivery::mergeability`),
 *  because the tempting bug is to treat "not obviously blocked" as permission.
 *
 *  Not `ConfirmDialog`: that component's two buttons are fixed, and this one's ACTION depends on
 *  what GitLab says. The confirmation shape it documents — name the specific branches, never "this
 *  item" — is kept. */
export function MergeConfirm({
  projectId,
  itemId,
  open,
  onOpenChange,
  busy,
  onMerge,
  provider = "gitlab",
}: {
  projectId: string;
  itemId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  onMerge: (opts: { sha: string; whenPipelineSucceeds: boolean }) => void;
  /** Item-level merge requests are GitLab-only today (ADR-0114 scopes them out for GitHub),
   *  so this defaults to "gitlab" — the caller only ever opens this dialog on that path. Kept
   *  as a prop, not hardcoded, so the copy stays correct if that scope ever widens. */
  provider?: DeliveryProvider;
}) {
  const nouns = providerNouns(provider);
  const { data, isPending, error } = useQuery({
    queryKey: ["merge-readiness", projectId, itemId],
    queryFn: () => api.itemMergeReadiness(projectId, itemId as number),
    enabled: open && itemId != null,
    // Never served from cache: a stale "ready" is the one answer this dialog must not give.
    gcTime: 0,
    staleTime: 0,
    retry: false,
  });

  const verdict = mergeability(data?.status);
  const target = data?.target_branch || "the target branch";
  const source = data?.source_branch || "this item's branch";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-label={`Merge this ${nouns.request}?`} className="max-w-md">
        <DialogHeader>
          <DialogTitle>Merge this {nouns.request}?</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2 px-4 text-[12.5px] leading-relaxed text-muted-foreground">
          {isPending ? (
            <p>Asking {nouns.hostName} whether this can merge…</p>
          ) : error ? (
            /* A failed read is not permission. Say what happened and offer nothing. */
            <p className="text-amber-600 dark:text-amber-400">
              Couldn&rsquo;t reach {nouns.hostName} to check whether this can merge, so nothing is
              offered.
            </p>
          ) : (
            <>
              <p className="text-foreground">
                <span className="font-mono">{source}</span> →{" "}
                <span className="font-mono">{target}</span>
              </p>
              <p
                className={
                  verdict.ready ? "text-foreground" : "text-amber-600 dark:text-amber-400"
                }
              >
                {verdict.headline}
              </p>
              {data?.error && (
                <p className="font-mono text-[11px] text-muted-foreground/80">{data.error}</p>
              )}
              <p className="text-[11.5px] text-muted-foreground/80">
                This merges on {nouns.hostName} and cannot be undone from here.
              </p>
            </>
          )}
        </div>
        <DialogFooter className="flex-row justify-end gap-2">
          <Button size="sm" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          {verdict.offer === "merge" && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => onMerge({ sha: data?.sha ?? "", whenPipelineSucceeds: false })}
            >
              {busy ? "Merging…" : `Merge into ${target}`}
            </Button>
          )}
          {verdict.offer === "auto-merge" && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => onMerge({ sha: data?.sha ?? "", whenPipelineSucceeds: true })}
            >
              {busy ? "Queueing…" : "Merge when the pipeline passes"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
