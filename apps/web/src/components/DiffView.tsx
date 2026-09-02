import { cn } from "@/lib/utils";

import { diffLineKind, parseDiff, type DiffLineKind } from "../lib/diff";
import { EmptyNote } from "./overview/bits";

// Parsing lives in lib/diff.ts (shared with the Changes tab). Line kinds are exposed as
// data-kind (the stable semantic hook tests target); colors ride the tone tokens.
const KIND_CLASS: Record<DiffLineKind, string> = {
  add: "text-success",
  del: "text-destructive",
  hunk: "bg-white/[0.02] text-muted-foreground/70",
  meta: "text-muted-foreground/70",
  ctx: "",
};

/** A readable unified diff: per-file collapsible blocks with a change summary. */
export function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) return <EmptyNote>No changes.</EmptyNote>;
  const files = parseDiff(diff);
  const adds = files.reduce((n, f) => n + f.adds, 0);
  const dels = files.reduce((n, f) => n + f.dels, 0);

  return (
    <div>
      <div className="mb-3 font-mono text-xs text-muted-foreground">
        {files.length} file{files.length === 1 ? "" : "s"} changed ·{" "}
        <span className="text-success">+{adds}</span>{" "}
        <span className="text-destructive">−{dels}</span>
      </div>
      {files.map((f, i) => (
        <details
          className="mb-2.5 overflow-hidden rounded-md border border-border"
          key={f.path + i}
          open={files.length <= 3}
        >
          <summary className="flex cursor-pointer list-none items-center gap-2.5 bg-card px-3 py-2 [&::-webkit-details-marker]:hidden">
            <span className="min-w-0 flex-1 font-mono text-[12.5px] [overflow-wrap:anywhere]">
              {f.path}
            </span>
            <span className="font-mono text-[11.5px]">
              <span className="text-success">+{f.adds}</span>{" "}
              <span className="text-destructive">−{f.dels}</span>
            </span>
          </summary>
          <div className="max-h-[460px] overflow-auto whitespace-pre border-t border-border bg-background px-3.5 py-3 font-mono text-[12.5px] leading-normal">
            {f.lines.map((line, j) => {
              const kind = diffLineKind(line);
              return (
                <span
                  key={j}
                  data-kind={kind === "ctx" ? undefined : kind}
                  className={cn("block", KIND_CLASS[kind])}
                >
                  {line || " "}
                </span>
              );
            })}
          </div>
        </details>
      ))}
    </div>
  );
}
