import { AlertTriangle } from "lucide-react";

import type { Project } from "../../api/client";
import { extractManualSteps } from "../../lib/manualSteps";
import { PmMarkdown } from "../pm/PmMarkdown";

/** Front-and-center surface for the work the delivery agent can't do (deleting a
 *  file, git/shell, installs…). The capability-aware PM keeps such work off the
 *  backlog and lists it in the brief; this pulls it up top so the stakeholder
 *  actually sees the manual steps instead of them being buried in the brief. */
export function ManualStepsCard({ project }: { project: Project }) {
  const steps = extractManualSteps(project.brief);
  if (!steps) return null;
  return (
    <section
      className="mb-4 flex gap-3 rounded-lg border border-white/12 bg-card p-4"
      style={{ borderLeft: "3px solid hsl(38 92% 48%)" }}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" style={{ color: "hsl(38 92% 48%)" }} />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-foreground">
          Needs your hands — steps the delivery agent can't do
        </p>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          Deleting, renaming, or moving files, git/shell commands, and installs are outside the
          delivery agent's capability. Do these yourself:
        </p>
        <div className="mt-2 text-[12px]">
          <PmMarkdown>{steps}</PmMarkdown>
        </div>
      </div>
    </section>
  );
}
