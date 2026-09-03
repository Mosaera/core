/** The connections table both panels render — same columns shape, different contents,
 *  because the two forges connect at genuinely different granularity: GitHub connects an
 *  *account* (one App installation covering many repositories), GitLab connects a *project*
 *  (one scoped token each). Forcing one into the other's row would be a tidier table and a
 *  less true one.
 *
 *  Every row here is derived at read time — from the installations GitHub reports and the
 *  projects this instance holds. Nothing is stored, so nothing can go stale. */
export function ConnectionsTable({
  columns,
  rows,
  empty,
}: {
  columns: string[];
  rows: { key: string; cells: React.ReactNode[] }[];
  empty: string;
}) {
  if (rows.length === 0)
    return (
      <div className="rounded-lg border border-dashed border-border/70 px-4 py-6 text-center text-[13px] text-muted-foreground">
        {empty}
      </div>
    );
  return (
    <div className="overflow-x-auto rounded-lg ring-1 ring-white/12">
      <table className="w-full min-w-[28rem] border-collapse text-left">
        <thead>
          <tr className="border-b border-border/60">
            {columns.map((c) => (
              <th
                key={c}
                scope="col"
                className="px-3 py-2 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-b border-border/40 last:border-0">
              {r.cells.map((cell, i) => (
                <td key={i} className="px-3 py-2.5 align-middle text-[13px] text-foreground/90">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
