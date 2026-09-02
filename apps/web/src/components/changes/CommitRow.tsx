import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { api, type BacklogItem, type HistoryRun } from "../../api/client";
import { backlogItemForRun, runCardBadge } from "../../lib/changes";
import { parseDiff } from "../../lib/diff";
import { historyRunHref, taskTitle, validationVerdict } from "../../lib/runs";
import { severityBadge } from "../StatusBadge";
import { CommitFileList } from "./CommitFileList";

// Content-sized metadata columns so the pill / sha / time line up in tight
// right-aligned columns across every row: chevron · title(flex) · pill · sha · time.
const ROW_COLS = "grid-cols-[1.25rem_minmax(0,1fr)_auto_auto_auto]";

function shortTime(at: string | null): string | null {
  if (!at) return null;
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return null;
  // 2-digit hour ("01:04 AM") so every time is the same width and aligns.
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** One change in the commits list: a flat, column-aligned row (chevron · title ·
 *  status · sha · time). The chevron toggles an inline description; the per-run
 *  diff + facts are fetched lazily on first expand (shared `["run", id]` cache).
 *
 *  The title is the item's SHORT name (redundancy audit 2026-08-22). It used to be the whole
 *  `run.task` paragraph — ~200 characters per row, identical across every attempt of one item,
 *  which made 71 rows unreadable and the one row that mattered unfindable. */
export function CommitRow({
  run,
  backlog,
  attemptLabel,
}: {
  run: HistoryRun;
  backlog: BacklogItem[];
  /** Prior-attempt row under an item header: the header owns the name, so this row says which
   *  attempt it is instead of repeating it. */
  attemptLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const badge = runCardBadge(run);
  const sha = run.commit_sha ? run.commit_sha.slice(0, 8) : null;
  const time = shortTime(run.created_at);
  const href = historyRunHref(run.id, run.project_id, run.task);
  const item = backlogItemForRun(run, backlog);

  const { data: detail, isLoading } = useQuery({
    queryKey: ["run", run.id],
    queryFn: () => api.runDetail(run.id),
    enabled: open,
  });
  const files = detail
    ? parseDiff(detail.repo_changes[0]?.diff ?? "").filter((f) => f.path)
    : [];
  const verdict = detail ? validationVerdict(detail, run) : null;

  return (
    <div className="border-b border-border/50 last:border-b-0">
      <div className={cn("grid items-center gap-x-4 py-3 pr-1", ROW_COLS)}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={open ? "Hide description" : "Show description"}
          className="rounded border-0 bg-transparent p-0.5 text-muted-foreground/60 hover:text-foreground"
        >
          {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </button>
        <Link
          to={href}
          className={cn(
            "truncate leading-snug hover:text-primary",
            attemptLabel
              ? "font-mono text-[11px] text-muted-foreground"
              : "text-sm font-medium",
          )}
        >
          {attemptLabel ?? (item ? `#${item.id} · ${item.title}` : taskTitle(run.task))}
        </Link>
        <span
          className={cn(
            "inline-block max-w-[9rem] justify-self-end truncate rounded-4xl border border-transparent px-2 py-0.5 font-mono text-[10px] uppercase leading-4",
            severityBadge(badge.tone),
          )}
        >
          {badge.label}
        </span>
        <span className="justify-self-end font-mono text-[11px] text-muted-foreground">
          {sha ?? ""}
        </span>
        <span className="justify-self-end font-mono text-[10px] text-muted-foreground/60">
          {time ?? ""}
        </span>
      </div>

      {open && (
        <div className="pb-3 pl-8 pr-3">
          {isLoading ? (
            <div className="flex flex-col gap-1.5">
              <Skeleton className="h-3 w-2/3" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-muted-foreground">
                {verdict && (
                  <span
                    className={
                      verdict.kind === "pass"
                        ? "text-success"
                        : verdict.kind === "failed"
                          ? "text-destructive"
                          : "text-primary"
                    }
                  >
                    {verdict.label}
                  </span>
                )}
                <span>
                  {run.iterations} {run.iterations === 1 ? "iteration" : "iterations"}
                </span>
                {run.termination_reason && (
                  <span className="text-primary/80">{run.termination_reason}</span>
                )}
              </div>
              {files.length > 0 ? (
                <CommitFileList files={files} />
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  No per-run diff was recorded for this change.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
