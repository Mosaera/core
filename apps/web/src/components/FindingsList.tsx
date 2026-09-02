import { cn } from "@/lib/utils";

/** One scanner-finding row; `tone` drives the left-rule color (red finding / green clean).
 *  Also used by ProjectDetailPage for its error state. */
export function FindingRow({
  rule,
  tone = "destructive",
  children,
}: {
  rule: string;
  tone?: "destructive" | "success";
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3 rounded-md border border-l-[3px] px-3.5 py-2.5 font-mono text-[12.5px]",
        tone === "destructive"
          ? "border-destructive/30 border-l-destructive/60 bg-destructive/10"
          : "border-success/30 border-l-success/60 bg-success/10",
      )}
    >
      <span className={cn("whitespace-nowrap", tone === "destructive" ? "text-destructive" : "text-success")}>
        {rule}
      </span>
      <span>{children}</span>
    </div>
  );
}

/** Parses the scanner's findings_text summary into rows.
 * Format: header line + "- [scanner:rule] path:line — message" lines. */
export function FindingsList({ text }: { text: string }) {
  const trimmed = (text ?? "").trim();
  const clean = !trimmed || trimmed === "No security findings.";
  if (clean) {
    return (
      <div className="grid gap-2">
        <FindingRow rule="clean" tone="success">
          No security findings.
        </FindingRow>
      </div>
    );
  }
  const rows = trimmed
    .split("\n")
    .filter((l) => l.trim().startsWith("-"))
    .map((l) => l.replace(/^-\s*/, ""));
  return (
    <div className="grid gap-2">
      {rows.map((row, i) => {
        const m = row.match(/^\[([^\]]+)\]\s*([^——]*)[——]?\s*(.*)$/);
        const rule = m?.[1] ?? "finding";
        const loc = (m?.[2] ?? "").trim();
        const msg = (m?.[3] ?? row).trim();
        return (
          <FindingRow rule={rule} key={i}>
            {loc && <span className="text-muted-foreground/70">{loc} </span>}
            {msg}
          </FindingRow>
        );
      })}
    </div>
  );
}
