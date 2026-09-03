import { File } from "lucide-react";

import { cn } from "@/lib/utils";

import { FILE_STATUS_LABEL, fileAnchorId, fileDiffStatus, type DiffFileStatus } from "../../lib/changes";
import type { FileDiff } from "../../lib/diff";
import { DiffBody } from "../changes/DiffBody";
import { StatPair } from "../changes/StatPair";

const STATUS_ICON_CLS: Record<DiffFileStatus, string> = {
  A: "text-success",
  M: "text-muted-foreground",
  D: "text-destructive",
};

/** The commit page's right pane: every changed file's diff, stacked flat (no
 *  cards) and anchored so the file tree can scroll to one. Each file leads with
 *  an icon + path + spelled-out status + counts, then a line-numbered diff. */
export function DiffPane({ files, selected }: { files: FileDiff[]; selected: string | null }) {
  return (
    <div className="flex min-w-0 flex-col divide-y divide-border/50">
      {files.map((f) => {
        const status = fileDiffStatus(f.lines);
        return (
          <section key={f.path} id={fileAnchorId(f.path)} className="scroll-mt-[76px] py-4 first:pt-0">
            <div
              className={cn(
                "mb-2 flex items-center gap-2 rounded-md px-1.5 py-1",
                selected === f.path && "bg-primary/5",
              )}
            >
              <File className={cn("size-3.5 shrink-0", STATUS_ICON_CLS[status])} />
              <span className="min-w-0 flex-1 truncate font-mono text-xs text-foreground/90">
                {f.path}
              </span>
              <span className="shrink-0 font-mono text-[10px] uppercase tracking-wide text-muted-foreground/60">
                {FILE_STATUS_LABEL[status]}
              </span>
              <StatPair additions={f.adds} deletions={f.dels} />
            </div>
            <div className="overflow-hidden rounded-md ring-1 ring-border/40">
              <DiffBody lines={f.lines} unbounded lineNumbers />
            </div>
          </section>
        );
      })}
    </div>
  );
}
