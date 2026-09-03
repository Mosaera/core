import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Rocket, TriangleAlert } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";

import { api, type Project } from "../../api/client";
import { ConsoleLabel } from "../overview/bits";
import { PmChatPanel } from "../pm/PmChatPanel";
import { SetupPanel } from "./SetupPanel";

/** The initialize phase: the ONLY tab shown before a project's backlog exists.
 *  Talk to Quincy to shape the project, then "Build the backlog" synthesizes the
 *  conversation and decomposes it — after which the full workspace unlocks. */
export function StartWorkspace({ project }: { project: Project }) {
  const qc = useQueryClient();
  const navigate = useNavigate();

  const { data: messagesData } = useQuery({
    queryKey: ["messages", project.id],
    queryFn: () => api.projectMessages(project.id),
  });
  const messages = messagesData?.messages ?? [];

  // A FAILED intake and a STARTING one are both status "draft" — the error is the only thing that
  // tells them apart. Without this the page rendered "Quincy is setting up the repository…" forever
  // on a typo'd repo URL, with the server's actual reason held in `project.error` and shown nowhere.
  const failed = project.status === "draft" && Boolean(project.error);
  const cloning = !failed && (project.status === "draft" || project.status === "drafting");
  const userMessages = messages.filter((m) => m.role === "user").length;

  const retry = useMutation({
    mutationFn: () => api.retryIntake(project.id),
    onSuccess: (resp) => qc.setQueryData(["project", project.id], resp),
  });

  const build = useMutation({
    mutationFn: () => api.approveProject(project.id),
    onSuccess: (resp) => {
      qc.setQueryData(["project", project.id], resp);
      navigate(`/projects/${project.id}/backlog`);
    },
  });

  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:-mb-16 lg:h-[calc(100dvh-88px)] lg:min-h-[460px] lg:grid-cols-[minmax(0,1fr)_340px] lg:items-stretch">
      <div className="min-h-0 min-w-0 lg:h-full">
        <PmChatPanel project={project} messages={messages} />
      </div>

      <div className="flex min-h-0 min-w-0 flex-col gap-3 overflow-y-auto">
        {/* The setup checklist sits BESIDE the chat, never in front of it (#121): the choices that
            decide whether a run can conclude, pre-filled from what the repo actually contains. */}
        <SetupPanel projectId={project.id} />
        <section className="flex flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-white/12">
          <ConsoleLabel>Start here</ConsoleLabel>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Tell Quincy what you want to build — goals, scope, constraints. When you've shaped the
            project together, build the backlog to open the full workspace.
          </p>
          <Button
            onClick={() => build.mutate()}
            disabled={failed || cloning || userMessages === 0 || build.isPending}
          >
            <Rocket className="size-4" />
            {build.isPending ? "Building…" : "Build the backlog"}
          </Button>
          {failed ? (
            <div className="flex flex-col gap-2" role="alert">
              <p className="flex items-start gap-1.5 text-xs text-destructive">
                <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                {/* The server's own words. A paraphrase would drop the one detail that says which
                    of "wrong URL", "no such branch" and "authentication" this actually was. */}
                <span className="min-w-0">{project.error}</span>
              </p>
              {/^.*(auth|denied|credential|403|401).*$/i.test(project.error ?? "") && (
                <p className="text-xs text-muted-foreground">
                  A private repository needs GitLab connected first — do that in Settings →
                  Integration, then try again.
                </p>
              )}
              <Button
                variant="outline"
                onClick={() => retry.mutate()}
                disabled={retry.isPending}
                className="self-start"
              >
                <RefreshCw className="size-4" />
                {retry.isPending ? "Retrying…" : "Try again"}
              </Button>
              {retry.isError && (
                <p className="text-xs text-destructive">
                  {retry.error instanceof Error ? retry.error.message : String(retry.error)}
                </p>
              )}
            </div>
          ) : cloning ? (
            <p className="text-xs text-muted-foreground">Quincy is setting up the repository…</p>
          ) : userMessages === 0 ? (
            <p className="text-xs text-muted-foreground">
              Describe your goal in the chat to get started.
            </p>
          ) : null}
          {build.isError && (
            <p role="alert" className="text-xs text-destructive">
              {build.error instanceof Error ? build.error.message : String(build.error)}
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
