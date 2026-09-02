import { FileText } from "lucide-react";

import type { Project } from "../../api/client";
import { CardHead, EmptyNote } from "../overview/bits";
import { PmMarkdown } from "../pm/PmMarkdown";

/** The project's document deliverables: the brief (read-only — approval lives
 *  on Overview, editing with the PM). Per-run delivery reports moved to each
 *  run's Receipt evidence tab (#63) — a report is a receipt, not a project doc. */
export function DocumentsPanel({ project }: { project: Project }) {
  return (
    <div className="flex min-h-0 flex-col gap-3 lg:overflow-y-auto lg:pr-0.5 lg:[scrollbar-color:var(--border)_transparent] lg:[scrollbar-width:thin]">
      <section
        aria-label="Project brief"
        className="flex flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-white/12"
      >
        <CardHead icon={FileText}>Project brief</CardHead>
        {project.brief ? (
          <div className="text-sm leading-relaxed">
            <PmMarkdown>{project.brief}</PmMarkdown>
          </div>
        ) : (
          <EmptyNote icon={FileText} hint="Draft it with the PM — it's reviewed and approved on Overview.">
            No brief yet
          </EmptyNote>
        )}
      </section>
    </div>
  );
}
