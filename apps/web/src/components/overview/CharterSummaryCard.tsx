import { useQuery } from "@tanstack/react-query";
import { ScrollText, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

import { api, type Project } from "../../api/client";
import { constraintRows } from "../../lib/charter";
import { BriefSheet } from "./BriefSheet";
import { CardHead, ConsoleLabel, EmptyNote } from "./bits";

/** The charter as a SLIM reference band (operator cut, 2026-08-13): goal + posture +
 *  two actions. The brief and the constraint list are reference material — one click
 *  away (drawer / Settings), never half the viewport. Editing lives in Settings. */
export function CharterSummaryCard({ project }: { project: Project }) {
  const [briefOpen, setBriefOpen] = useState(false);
  const { data: charter } = useQuery({
    queryKey: ["charter", project.id],
    queryFn: () => api.getCharter(project.id),
  });
  const goal = charter?.goal || project.goal;
  const rows = constraintRows(charter?.constraints);

  return (
    <Card size="sm">
      <CardHeader className="grid-cols-[1fr_auto]">
        <CardHead icon={ScrollText}>Charter</CardHead>
        {charter?.posture && (
          <span
            className="flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wide text-muted-foreground"
            title="Autonomy posture"
          >
            <ShieldCheck className="size-3.5" />
            {charter.posture}
          </span>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-2.5">
        {goal ? (
          <p className="line-clamp-2 text-sm font-medium leading-relaxed">{goal}</p>
        ) : (
          <EmptyNote>No goal recorded for this project yet.</EmptyNote>
        )}
        {/* Constraints as ROWS, not a 2.4KB paragraph behind a disclosure (owner, 2026-08-22).
            The split is deterministic — the stored text is an enumerated list by construction and
            `constraintRows` never paraphrases. When the prose is NOT enumerated it yields a single
            row and this renders it as the paragraph it is, rather than inventing structure. */}
        {rows.length > 0 && (
          <div className="flex flex-col gap-1">
            <ConsoleLabel className="text-[10px]">
              {rows.length > 1 ? `Constraints · ${rows.length}` : "Constraints"}
            </ConsoleLabel>
            {rows.length === 1 ? (
              <p className="max-h-40 overflow-y-auto rounded-md bg-muted/30 p-2.5 text-[12.5px] leading-relaxed">
                {rows[0].text}
              </p>
            ) : (
              <ul className="flex max-h-64 flex-col divide-y divide-border/50 overflow-y-auto rounded-md bg-muted/20 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
                {rows.map((r, i) => (
                  <li key={i} className="flex flex-col gap-0.5 px-2.5 py-1.5">
                    <span className="text-[12.5px] font-medium leading-snug">{r.label}</span>
                    {r.text !== r.label && (
                      <span className="text-[12px] leading-snug text-muted-foreground">
                        {r.text}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          {project.brief && (
            <Button size="sm" variant="secondary" onClick={() => setBriefOpen(true)}>
              View full brief
            </Button>
          )}
          <Link
            to={`/projects/${project.id}/settings`}
            className="font-mono text-xs text-primary underline-offset-2 hover:underline"
          >
            Edit charter
          </Link>
        </div>
      </CardContent>
      <BriefSheet project={project} open={briefOpen} onClose={() => setBriefOpen(false)} />
    </Card>
  );
}
