import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

/** The three remote-mutating confirms for the Branches panel (A3, ADR-0103 Phase 4), split out
 *  of `DeliveryWorkspace` to keep that file under the 500-line ratchet — same confirm-then-fire
 *  shape it already used, moved rather than rewritten. */
export type BranchConfirm =
  | { kind: "prune" }
  | { kind: "branch"; name: string }
  | { kind: "retarget"; id: number }
  | null;

export function BranchConfirmDialogs({
  confirm,
  onOpenChange,
  base,
  hostName,
  prunable,
  deleteBranch,
  deleteBusy,
  retarget,
  retargetBusy,
  prune,
  pruneBusy,
}: {
  confirm: BranchConfirm;
  onOpenChange: (open: boolean) => void;
  base: string;
  /** The forge's product name (providerNouns().hostName) — "Delete this branch on GitLab?" only
   *  reads true for GitLab; this panel is gitlab-gated but the copy should still say the truth. */
  hostName: string;
  prunable: string[];
  deleteBranch: (name: string) => void;
  deleteBusy: boolean;
  retarget: (id: number) => void;
  retargetBusy: boolean;
  prune: () => void;
  pruneBusy: boolean;
}) {
  return (
    <>
      <ConfirmDialog
        open={confirm?.kind === "branch"}
        onOpenChange={onOpenChange}
        title={`Delete this branch on ${hostName}?`}
        confirmLabel="Delete branch"
        busyLabel="Deleting…"
        busy={deleteBusy}
        onConfirm={() => {
          if (confirm?.kind === "branch") deleteBranch(confirm.name);
          onOpenChange(false);
        }}
      >
        <p>
          <span className="font-mono text-foreground">
            {confirm?.kind === "branch" ? confirm.name : ""}
          </span>{" "}
          will be deleted from the remote. This can&rsquo;t be undone from Mosaera — any commits on
          it that aren&rsquo;t merged elsewhere are gone.
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        open={confirm?.kind === "retarget"}
        onOpenChange={onOpenChange}
        title={`Retarget this merge request to ${base}?`}
        confirmLabel={`Retarget to ${base}`}
        busyLabel="Retargeting…"
        destructive={false}
        busy={retargetBusy}
        onConfirm={() => {
          if (confirm?.kind === "retarget") retarget(confirm.id);
          onOpenChange(false);
        }}
      >
        <p>
          The branch this merge request targeted is gone, so it can&rsquo;t merge. Repointing it at{" "}
          <span className="font-mono text-foreground">{base}</span> makes it mergeable again.
        </p>
        <p className="mt-2">
          Its diff will be recalculated against {base}, so it may now show work from earlier items
          that was never reviewed in this merge request. Read the diff before merging.
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        open={confirm?.kind === "prune"}
        onOpenChange={onOpenChange}
        title="Prune merged branches?"
        confirmLabel="Prune branches"
        busyLabel="Pruning…"
        busy={pruneBusy}
        onConfirm={() => {
          prune();
          onOpenChange(false);
        }}
      >
        {/* Naming them is the point: this is a BULK remote delete and the operator otherwise
            learns what it hit only from the after-the-fact `pruned …` line. */}
        {prunable.length > 0 ? (
          <>
            <p>These branches will be deleted from the remote:</p>
            <ul className="mt-1.5 flex flex-col gap-0.5 font-mono text-[11.5px] text-foreground">
              {prunable.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          </>
        ) : (
          <p>No merged item branches to clean up.</p>
        )}
        <p className="mt-2">
          A branch still targeted by an open merge request is refused server-side, so the result
          may be shorter than this list — never longer.
        </p>
      </ConfirmDialog>
    </>
  );
}
