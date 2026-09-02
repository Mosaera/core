import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

import { api, type Project } from "../../api/client";
import { artifactsSummary } from "../../lib/artifacts";
import { DocumentsPanel } from "./DocumentsPanel";
import { ProducedFilesPanel } from "./ProducedFilesPanel";
import { ProjectFilePreview } from "./ProjectFilePreview";

/** Artifacts tab: the deliverables surface — what the project has produced
 *  that the user can take away (files, patch, brief, run reports). The repo
 *  delta belongs to Changes and execution diagnostics to Runs; this tab only
 *  hands off. Full-height workspace, panels scroll internally. */
export function ArtifactsWorkspace({ project }: { project: Project }) {
  // Same key + fn as Overview's pipeline artifact count — the caches share.
  const { data } = useQuery({
    queryKey: ["project-files", project.id],
    queryFn: () => api.projectFiles(project.id),
  });
  const files = data?.files ?? [];
  const [previewPath, setPreviewPath] = useState<string | null>(null);

  return (
    <div className="flex min-h-0 flex-col gap-4 lg:-mb-16 lg:h-[calc(100dvh-88px)] lg:min-h-[460px]">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h1 className="font-sans text-2xl font-bold tracking-tight">Artifacts</h1>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {data ? artifactsSummary(files.length, Boolean(project.brief)) : "loading…"}
        </span>
        <div className="ms-auto flex items-center gap-2">
          {files.length > 0 && (
            <Button
              size="sm"
              variant="secondary"
              nativeButton={false}
              render={<a href={api.projectPatchUrl(project.id)} download />}
            >
              <Download data-icon="inline-start" />
              Download patch
            </Button>
          )}
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 items-start gap-3 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-stretch">
        <ProducedFilesPanel project={project} files={files} onPreview={setPreviewPath} />
        <DocumentsPanel project={project} />
      </div>

      {previewPath && (
        <ProjectFilePreview
          projectId={project.id}
          path={previewPath}
          onClose={() => setPreviewPath(null)}
        />
      )}
    </div>
  );
}
