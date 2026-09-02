/* Tiny shared pieces for the Overview dashboard: console-style card header,
   severity dot, and intentional empty states. */

import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

import type { Severity } from "../../lib/overview";

export function ConsoleLabel({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Uniform card header: small identity icon + eyebrow label. Neutral tone for
 *  informational cards; amber reserved for action/attention cards. */
export function CardHead({
  icon: Icon,
  tone = "neutral",
  children,
}: {
  icon: LucideIcon;
  tone?: "neutral" | "amber";
  children: React.ReactNode;
}) {
  return (
    <ConsoleLabel
      className={cn("flex items-center gap-2", tone === "amber" && "text-primary/90")}
    >
      <Icon
        className={cn(
          "size-4 shrink-0",
          tone === "neutral" ? "text-muted-foreground" : "text-primary",
        )}
      />
      {children}
    </ConsoleLabel>
  );
}

const DOT: Record<Severity, string> = {
  green: "bg-success",
  amber: "bg-primary",
  red: "bg-destructive",
};

export function SeverityDot({ severity, className }: { severity: Severity; className?: string }) {
  return <span className={cn("size-2 shrink-0 rounded-full", DOT[severity], className)} aria-hidden />;
}

/** Intentional empty state: quiet icon, primary line, optional secondary line. */
export function EmptyNote({
  icon: Icon,
  children,
  hint,
}: {
  icon?: LucideIcon;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex flex-col items-start gap-1 py-2">
      {Icon && <Icon className="mb-0.5 size-4 text-muted-foreground/50" />}
      <p className="text-sm text-muted-foreground">{children}</p>
      {hint && <p className="text-xs text-muted-foreground/60">{hint}</p>}
    </div>
  );
}

/** Spend-vs-cap meter (shared by the Overview budgets card and project Settings).
 *  Tone follows the enforcement thresholds: green under 80%, amber at warn, red at cap. */
export function BudgetBar({
  label,
  spent,
  cap,
  fmt = (n: number) => n.toLocaleString(),
}: {
  label: string;
  spent: number;
  cap: number;
  fmt?: (n: number) => string;
}) {
  const pct = cap > 0 ? Math.min(spent / cap, 1) : 0;
  const tone = spent >= cap ? "bg-destructive" : pct >= 0.8 ? "bg-primary" : "bg-success";
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between font-mono text-[11px]">
        <span className="text-muted-foreground">{label}</span>
        <span className="text-foreground/90">
          {fmt(spent)} / {fmt(cap)}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-foreground/10">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct * 100}%` }} />
      </div>
    </div>
  );
}
