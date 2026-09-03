import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

import type { Project } from "../../api/client";
import { attentionItems } from "../../lib/overview";
import { SeverityDot } from "./bits";

/** CTA label per destination — every row names its one action. */
const GO: Record<string, string> = {
  runs: "Review run",
  backlog: "Open backlog",
  "delivery?view=changes": "Review changes",
  settings: "Edit budget",
};

/** What needs YOU: one row per actionable project-level fact, one action per row.
 *
 *  Mounted as a subsection of `DecisionBand` (5C, the page's single "needs you" region) — a quiet
 *  single line when nothing does UNLESS a sibling subsection (a server decision, the worklist)
 *  already has something to say, in which case `hideEmpty` drops this to nothing rather than
 *  adding a second, contradictory "all clear" beside real work. */
export function AttentionStrip({
  project,
  mrState,
  hideEmpty = false,
}: {
  project: Project;
  mrState: string | null;
  hideEmpty?: boolean;
}) {
  const items = attentionItems(project, mrState);
  if (items.length === 0) {
    if (hideEmpty) return null;
    return (
      <div className="mb-4 flex items-center gap-2.5 rounded-lg bg-card px-4 py-2.5 ring-1 ring-white/12">
        <SeverityDot severity="green" />
        <span className="text-[13px] text-muted-foreground">
          Nothing needs you — the record is quiet.
        </span>
      </div>
    );
  }
  return (
    <ul className="mb-4 flex flex-col gap-1.5 rounded-lg bg-card px-4 py-2.5 ring-1 ring-white/12">
      {items.map((item, idx) => (
        <li key={idx} className="flex items-center gap-2.5">
          <SeverityDot severity={item.severity} />
          <span
            className="min-w-0 flex-1 truncate text-[13px] font-medium leading-snug"
            title={item.detail ?? item.text}
          >
            {item.text}
          </span>
          {item.to && (
            <Link
              to={`/projects/${project.id}/${item.to}`}
              className="flex shrink-0 items-center gap-1 font-mono text-xs text-primary underline-offset-2 hover:underline"
            >
              {GO[item.to] ?? "Open"} <ArrowRight className="size-3" />
            </Link>
          )}
        </li>
      ))}
    </ul>
  );
}
