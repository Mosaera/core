import { CircleDollarSign } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import type { GatePayload } from "../../api/client";

const DIM_LABEL: Record<string, string> = {
  usd: "spend",
  tokens: "token",
  tool_calls: "tool-call",
};

function spentLabel(breach: string, spent: number, cap: number): string {
  if (breach === "usd") return `$${spent.toFixed(4)} of $${cap}`;
  if (breach === "tokens") return `${spent.toLocaleString()} of ${cap.toLocaleString()} tokens`;
  return `${spent} of ${cap} tool calls`;
}

/** A run that crossed its spend ceiling parks here: continue with more headroom,
 *  or stop and keep the work so far. Approve raises the ceiling (grants another
 *  budget's worth); deny stops the run. Reuses the same approve endpoint as the
 *  delivery gate (action === "budget"). */
export function BudgetGate({
  gate,
  busy,
  onDecide,
  variant = "card",
}: {
  gate: GatePayload;
  busy: boolean;
  onDecide: (approve: boolean, feedback: string) => void;
  /** "hero" strips the card chrome; decision semantics identical. */
  variant?: "card" | "hero";
}) {
  const breach = gate.breach ?? "usd";
  const spent = gate.spent ?? 0;
  const cap = gate.cap ?? 0;

  return (
    <section
      role="alertdialog"
      aria-label="budget reached"
      className={
        variant === "hero"
          ? "flex flex-col gap-3"
          : "flex flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-primary/40"
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge className="border-transparent bg-primary/15 font-mono text-[10px] uppercase text-primary">
          <CircleDollarSign className="size-3" />
          Budget reached
        </Badge>
        <p className="text-sm font-medium">This run hit its {DIM_LABEL[breach] ?? "spend"} limit</p>
      </div>
      <p className="text-sm leading-relaxed text-muted-foreground">
        Spent <span className="font-mono text-foreground">{spentLabel(breach, spent, cap)}</span>
        {typeof gate.calls === "number" ? ` over ${gate.calls} calls` : ""}
        {typeof gate.elapsed_s === "number" ? ` in ${gate.elapsed_s}s` : ""}. Continue with more
        headroom, or stop the run and keep the work done so far.
      </p>
      {(gate.raised_before ?? 0) > 0 && (
        <p className="text-[12px] font-medium" style={{ color: "hsl(38 92% 48%)" }}>
          ⚠ You've already raised this budget {gate.raised_before}×. If the run isn't converging,
          more budget won't help — consider stopping.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={busy} onClick={() => onDecide(true, "")}>
          Continue — raise limit
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-muted-foreground"
          disabled={busy}
          onClick={() => onDecide(false, "")}
        >
          Stop run
        </Button>
      </div>
    </section>
  );
}
