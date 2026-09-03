/** Shared +additions / −deletions chip. `null`/`null` renders as "binary". */
export function StatPair({
  additions,
  deletions,
}: {
  additions: number | null;
  deletions: number | null;
}) {
  if (additions === null && deletions === null) {
    return <span className="font-mono text-[10px] text-muted-foreground/60">binary</span>;
  }
  return (
    <span className="font-mono text-[10px] tabular-nums">
      <span className="text-success">+{additions ?? 0}</span>{" "}
      <span className="text-destructive">−{deletions ?? 0}</span>
    </span>
  );
}
