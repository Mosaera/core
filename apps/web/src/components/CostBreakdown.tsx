import type { CostBreakdownRow } from "../api/client";

/** A compact cost breakdown list (by agent or by model). Each row shows the
 *  dollar cost for a paid model, or the token count when the model is free —
 *  tokens and cost are never conflated.
 *
 *  A SHADOW row is an on-box model priced only to make the burn visible: the money is imputed
 *  and owed to nobody, so it is labelled rather than shown as plain spend. Without the label a
 *  local run and a billed run look identical the moment shadow prices are configured. */
export function CostBreakdown({
  label,
  rows,
  nameKey,
}: {
  label: string;
  rows: CostBreakdownRow[];
  nameKey: "agent" | "model";
}) {
  if (rows.length === 0) return null;
  return (
    <div className="flex flex-col gap-0.5">
      <p className="font-mono text-[9px] uppercase tracking-[0.12em] text-muted-foreground/50">
        {label}
      </p>
      {rows.map((r) => (
        <div
          key={r[nameKey] ?? ""}
          className="flex items-center justify-between gap-2 text-[11px]"
        >
          <span className="min-w-0 truncate text-foreground/80">{r[nameKey] || "unknown"}</span>
          <span className="shrink-0 font-mono tabular-nums text-muted-foreground">
            {r.usd > 0
              ? `${r.shadow ? "~" : ""}$${r.usd.toFixed(4)}${r.shadow ? " shadow" : ""}`
              : `${r.total_tokens.toLocaleString()} tok`}
          </span>
        </div>
      ))}
    </div>
  );
}
