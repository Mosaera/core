import { cn } from "@/lib/utils";

import { fileDiffStatus, type DiffFileStatus } from "../../lib/changes";
import type { FileDiff } from "../../lib/diff";
import { StatPair } from "./StatPair";
import { TONE_BADGE } from "../StatusBadge";

const STATUS_CLS: Record<DiffFileStatus, string> = {
  A: TONE_BADGE.success,
  M: TONE_BADGE.amber,
  D: TONE_BADGE.destructive,
};

/** The shadcn.io `ai/commit`-style changed-file list: an A/M/D status chip,
 *  the path, and its +/− counts. Flat (no folder grouping) — the row is a
 *  glance; the full tree lives on the commit page. */
export function CommitFileList({ files }: { files: FileDiff[] }) {
  return (
    <ul className="flex flex-col gap-0.5">
      {files.map((f) => {
        const status = fileDiffStatus(f.lines);
        return (
          <li key={f.path} className="flex items-center gap-2 py-0.5">
            <span
              className={cn(
                "flex size-4 shrink-0 items-center justify-center rounded font-mono text-[9px] font-semibold",
                STATUS_CLS[status],
              )}
              title={{ A: "added", M: "modified", D: "deleted" }[status]}
            >
              {status}
            </span>
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-foreground/90">
              {f.path}
            </span>
            <StatPair additions={f.adds} deletions={f.dels} />
          </li>
        );
      })}
    </ul>
  );
}
