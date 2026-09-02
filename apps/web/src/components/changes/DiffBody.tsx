import { cn } from "@/lib/utils";

import { annotateDiff, diffLineKind, type DiffLineKind } from "../../lib/diff";

const KIND_CLS: Record<DiffLineKind, string> = {
  add: "bg-success/10 text-success",
  del: "bg-destructive/10 text-destructive",
  hunk: "bg-muted/40 text-primary/80",
  meta: "text-muted-foreground/50",
  ctx: "text-foreground/80",
};

/** Token-styled unified-diff lines. `unbounded` drops the internal height cap
 *  for the commit page (which scrolls the pane); `lineNumbers` renders the
 *  old/new line-number gutters for the primary commit-page diff. */
export function DiffBody({
  lines,
  unbounded,
  lineNumbers,
}: {
  lines: string[];
  unbounded?: boolean;
  lineNumbers?: boolean;
}) {
  const wrap = cn(
    "font-mono text-[11px] leading-relaxed",
    lineNumbers ? "" : "rounded-md p-2",
    unbounded
      ? ""
      : "max-h-96 overflow-y-auto [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]",
  );

  if (lineNumbers) {
    // Drop git meta noise (index/mode/---/+++); the file header already carries
    // the path + status. Strip the leading +/-/space — the gutter + tint convey it.
    const rows = annotateDiff(lines).filter((r) => r.kind !== "meta");
    return (
      <div className={wrap}>
        {rows.map((r, i) => (
          <div key={i} className={cn("grid grid-cols-[2.5rem_2.5rem_1fr]", KIND_CLS[r.kind])}>
            <span className="select-none px-1.5 text-right text-[10px] tabular-nums text-muted-foreground/40">
              {r.oldNo ?? ""}
            </span>
            <span className="select-none border-r border-border/40 px-1.5 text-right text-[10px] tabular-nums text-muted-foreground/40">
              {r.newNo ?? ""}
            </span>
            <span className="whitespace-pre-wrap break-all px-2">
              {(r.kind === "hunk" ? r.text : r.text.slice(1)) || " "}
            </span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className={wrap}>
      {lines.map((line, i) => (
        <div key={i} className={`whitespace-pre-wrap break-all ${KIND_CLS[diffLineKind(line)]}`}>
          {line || " "}
        </div>
      ))}
    </div>
  );
}
