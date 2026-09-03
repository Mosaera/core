import { Download, Eye, FileText, Package } from "lucide-react";

import { Button } from "@/components/ui/button";

import { api, type Project } from "../../api/client";
import { groupPathsByFolder, previewKind } from "../../lib/artifacts";
import { CardHead, EmptyNote } from "../overview/bits";

/** The project's produced files, grouped by folder. Deliverables framing only:
 *  preview + download — no diff stats, no merge language (that's Changes). */
export function ProducedFilesPanel({
  project,
  files,
  onPreview,
}: {
  project: Project;
  files: string[];
  onPreview: (path: string) => void;
}) {
  const groups = groupPathsByFolder(files);

  return (
    <section
      aria-label="Produced files"
      className="flex min-h-0 flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-white/12"
    >
      <CardHead icon={Package}>Produced files</CardHead>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-0.5 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
        {files.length === 0 ? (
          <EmptyNote icon={Package} hint="Run a backlog item to produce deliverables.">
            No produced files yet
          </EmptyNote>
        ) : (
          groups.map((group) => (
            <div key={group.name} className="flex flex-col gap-1">
              <span className="font-mono text-[11px] font-medium text-foreground/80">
                {group.name}
                <span className="ml-2 tabular-nums text-muted-foreground/60">
                  {group.files.length}
                </span>
              </span>
              <div className="flex flex-col">
                {group.files.map((path) => (
                  <div
                    key={path}
                    className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-muted/40"
                  >
                    <FileText className="size-3.5 shrink-0 text-muted-foreground/60" />
                    <span className="min-w-0 flex-1 truncate font-mono text-xs text-foreground/90">
                      {path}
                    </span>
                    {previewKind(path) !== "none" && (
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        aria-label={`Preview ${path}`}
                        className="text-muted-foreground"
                        onClick={() => onPreview(path)}
                      >
                        <Eye />
                      </Button>
                    )}
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      aria-label={`Download ${path}`}
                      className="text-muted-foreground"
                      nativeButton={false}
                      render={<a href={api.projectFileUrl(project.id, path)} download />}
                    >
                      <Download />
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
