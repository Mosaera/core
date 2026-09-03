import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

import type { Project } from "../../api/client";
import { PmMarkdown } from "../pm/PmMarkdown";

/** Right-side drawer showing the complete project brief as markdown, opened
 *  from the Overview objective card so the full brief is reachable without
 *  leaving the page (mirrors ChangeDetailSheet). */
export function BriefSheet({
  project,
  open,
  onClose,
}: {
  project: Project;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        className="overflow-y-auto sm:max-w-lg [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]"
      >
        <SheetHeader>
          <SheetTitle>Project brief</SheetTitle>
          {project.goal && <SheetDescription>{project.goal}</SheetDescription>}
        </SheetHeader>
        <div className="px-4 pb-6 text-sm leading-relaxed">
          {project.brief ? (
            <PmMarkdown>{project.brief}</PmMarkdown>
          ) : (
            <p className="text-muted-foreground">No brief has been drafted yet.</p>
          )}
          <div className="mt-4">
            <Button
              size="sm"
              variant="secondary"
              nativeButton={false}
              render={<Link to={`/projects/${project.id}/delivery?view=artifacts`} onClick={onClose} />}
            >
              Open in Artifacts
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
