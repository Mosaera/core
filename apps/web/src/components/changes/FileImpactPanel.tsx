import { ChevronDown, ChevronRight, FolderClosed } from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";

import { parseDiff, type FileDiff } from "../../lib/diff";
import { groupFilesByFolder, type FileStat } from "../../lib/changes";
import { ConsoleLabel, EmptyNote } from "../overview/bits";
import { DiffBody } from "./DiffBody";
import { StatPair } from "./StatPair";

/** Accumulated file changes vs the source default branch, grouped by top-level
 *  folder. "Impact" here is strictly file paths and line counts — no analysis.
 *  A row expands to that file's real diff lines; only expanded bodies mount. */
export function FileImpactPanel({
  base,
  diffText,
  stats,
  partial,
}: {
  base: string;
  diffText: string;
  stats: FileStat[];
  partial: boolean;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const groups = useMemo(() => groupFilesByFolder(stats), [stats]);
  const bodies = useMemo(() => {
    const map = new Map<string, FileDiff>();
    for (const f of parseDiff(diffText)) if (f.path) map.set(f.path, f);
    return map;
  }, [diffText]);

  function toggle(path: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  return (
    <section
      aria-label="File impact"
      className="flex min-h-0 flex-col gap-2 rounded-lg bg-card p-3 ring-1 ring-white/12"
    >
      {/* No totals line here: the page summary directly above already states
          "N files · +A −B vs {base}" — one fact, one render (redundancy audit 2026-08-22).
          This panel states only what it adds: the per-folder structure. */}
      <header className="flex shrink-0 flex-col gap-1">
        <ConsoleLabel>File impact</ConsoleLabel>
        {partial && (
          <p className="text-[11px] text-primary">
            Diff truncated at 200,000 characters — the file list and line counts below are
            partial.
          </p>
        )}
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-0.5 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
        {stats.length === 0 ? (
          <EmptyNote icon={FolderClosed} hint="Validation may have run without modifying the repository.">
            No files changed vs {base} yet.
          </EmptyNote>
        ) : (
          groups.map((group) => (
            <div key={group.name} className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <FolderClosed className="size-3.5 shrink-0 text-muted-foreground/60" />
                <span className="font-mono text-[11px] font-medium text-foreground/80">
                  {group.name}
                </span>
                <span className="font-mono text-[10px] tabular-nums text-muted-foreground/60">
                  {group.files.length}
                </span>
                <span className="ml-auto font-mono text-[10px] tabular-nums">
                  <span className="text-success">+{group.adds}</span>{" "}
                  <span className="text-destructive">−{group.dels}</span>
                </span>
              </div>
              <div className="flex flex-col">
                {group.files.map((file) => {
                  const open = expanded.has(file.path);
                  const body = bodies.get(file.path);
                  return (
                    <div key={file.path} className="flex flex-col">
                      <button
                        type="button"
                        onClick={() => toggle(file.path)}
                        aria-expanded={open}
                        className={cn(
                          "flex items-center gap-1.5 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-muted/40",
                          open && "bg-muted/30",
                        )}
                      >
                        {open ? (
                          <ChevronDown className="size-3 shrink-0 text-muted-foreground/60" />
                        ) : (
                          <ChevronRight className="size-3 shrink-0 text-muted-foreground/60" />
                        )}
                        <span className="min-w-0 flex-1 truncate font-mono text-xs text-foreground/90">
                          {file.path}
                        </span>
                        <StatPair additions={file.additions} deletions={file.deletions} />
                      </button>
                      {open &&
                        (body ? (
                          <div className="mb-1 ml-4">
                            <DiffBody lines={body.lines} />
                          </div>
                        ) : (
                          <p className="mb-1 ml-6 text-[11px] text-muted-foreground">
                            Diff body unavailable — the accumulated diff was truncated.
                          </p>
                        ))}
                    </div>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

