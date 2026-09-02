import {
  ArrowDownUp,
  GitMerge,
  Link2,
  Lock,
  LockOpen,
  Plus,
  Sparkles,
  Split,
  Trash2,
  Wand2,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

import type { BacklogItem, ChangesetOp } from "../../api/client";
import { CardHead } from "../overview/bits";

/** Human-readable presentation of one changeset op: an icon, a one-line
 *  headline, and optional detail lines. Titles are resolved from the live
 *  backlog so ids read as names. */
export function describeOp(op: ChangesetOp, titleOf: (id: number) => string): {
  icon: LucideIcon;
  headline: string;
  detail: string[];
  why?: string;
} {
  switch (op.op) {
    case "add":
      return {
        icon: Plus,
        headline: `Add ${op.title}`,
        detail: op.description ? [op.description] : [],
        why: op.why,
      };
    case "reorder":
      return {
        icon: ArrowDownUp,
        headline: `Reorder ${op.ordered_ids.length} item${op.ordered_ids.length === 1 ? "" : "s"}`,
        detail: op.ordered_ids.map((id, i) => `${i + 1}. ${titleOf(id)}`),
        why: op.why,
      };
    case "enhance": {
      const fields = [
        op.title !== undefined ? "title" : null,
        op.description !== undefined ? "description" : null,
        op.acceptance !== undefined ? "acceptance" : null,
      ].filter(Boolean);
      return {
        icon: Wand2,
        headline: `Enhance ${titleOf(op.id)}`,
        detail: fields.length ? [`Rewrites: ${fields.join(", ")}`] : [],
        why: op.why,
      };
    }
    case "lock":
      return {
        icon: Lock,
        headline: `Lock ${titleOf(op.id)}`,
        detail: op.reason ? [op.reason] : [],
      };
    case "unlock":
      return {
        icon: LockOpen,
        headline: `Unlock ${titleOf(op.id)}`,
        detail: [],
        why: op.why,
      };
    case "set_dependencies":
      return {
        icon: Link2,
        headline: `Set dependencies for ${titleOf(op.id)}`,
        detail: [
          op.depends_on.length
            ? `Depends on ${op.depends_on.map(titleOf).join(", ")}`
            : "Clears all dependencies",
        ],
        why: op.why,
      };
    case "split":
      return {
        icon: Split,
        headline: `Split ${titleOf(op.id)} into ${op.parts.length} item${op.parts.length === 1 ? "" : "s"}`,
        detail: op.parts.map((p, i) => `${i + 1}. ${p.title}`),
        why: op.why,
      };
    case "merge":
      return {
        icon: GitMerge,
        headline: `Merge ${op.sources.map(titleOf).join(", ")} into ${titleOf(op.target)}`,
        detail: op.title !== undefined ? [`Merged title: ${op.title}`] : [],
        why: op.why,
      };
    case "delete":
      return {
        icon: Trash2,
        headline: `Delete ${titleOf(op.id)}`,
        detail: [],
        why: op.why,
      };
  }
}

/** Review panel for a proposed curation changeset (from Quincy). Nothing is
 *  applied until Approve; Discard drops the proposal. Modeled on the PM
 *  proposal card's approve-flow and styling, generalized to the op types. */
export function ChangesetReview({
  ops,
  items,
  onApprove,
  onDiscard,
  applying,
  error,
}: {
  ops: ChangesetOp[];
  items: BacklogItem[];
  onApprove: () => void;
  onDiscard: () => void;
  applying: boolean;
  error?: string | null;
}) {
  const titleOf = (id: number) =>
    items.find((i) => i.id === id)?.title ?? `#${id}`;

  return (
    <Card size="sm" className="ring-primary/30">
      <CardHeader>
        <CardHead icon={Sparkles} tone="amber">
          Proposed curation · {ops.length} change{ops.length === 1 ? "" : "s"}
        </CardHead>
      </CardHeader>
      <CardContent className="flex flex-col gap-2.5">
        {ops.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            Quincy found nothing to change — the backlog already looks well-ordered.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {ops.map((op, i) => {
              const { icon: Icon, headline, detail, why } = describeOp(op, titleOf);
              return (
                <li key={i} className="flex items-start gap-2">
                  <Icon className="mt-0.5 size-4 shrink-0 text-primary" />
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-[13px] font-medium leading-snug">{headline}</span>
                    {detail.map((d, j) => (
                      <span key={j} className="text-xs leading-snug text-muted-foreground">
                        {d}
                      </span>
                    ))}
                    {why && (
                      <span className="text-xs italic leading-snug text-muted-foreground/70">
                        {why}
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}

        <div className="flex flex-wrap gap-2 pt-0.5">
          <Button size="sm" onClick={onApprove} disabled={applying || ops.length === 0}>
            {applying ? "Applying…" : "Approve"}
          </Button>
          <Button size="sm" variant="ghost" onClick={onDiscard} disabled={applying}>
            Discard
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
