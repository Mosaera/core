import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import { api, type Project } from "../../api/client";
import { sessionsApi } from "../../api/sessions";
import { PmChatPanel } from "./PmChatPanel";
import { PmSessionBar } from "./PmSessionBar";

/** PM tab: Overview tells the customer what's happening — this is where they
 *  steer. The chat owns the page outright — the support rail was removed
 *  2026-08-20 because it had stopped earning its column: `WaitingOnYouCard`
 *  derived pending decisions CLIENT-side from `project.backlog`, which ADR-0105
 *  superseded with a server-derived card (so it cannot be summoned by anything
 *  Quincy was persuaded to say), and spend / current-focus / attention each
 *  duplicated an Overview card. Those decision cards then left the transcript
 *  too (2026-08-22) for the Overview's "Waiting on you" band: derived cards with
 *  no dismissal and no refetch were furniture in a conversation, not
 *  notifications. The chat still invalidates their query, because a chat turn
 *  can resolve one. `PmContextCard` went with them,
 *  which does cost the only browsable list of uploaded context files — the files
 *  are still uploaded and still used, and each reply's "Used context" line still
 *  reports what it drew on.
 *  Sessions (issue #30) thread the conversation: each is scoped history, while
 *  project knowledge stays shared. The selected session lives in the URL
 *  (`?session=`) so switching/refresh is stable and shareable. */
export function PmWorkspace({ project }: { project: Project }) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();

  const { data: sessionsData } = useQuery({
    queryKey: ["sessions", project.id],
    queryFn: () => sessionsApi.list(project.id),
  });
  const sessions = useMemo(() => sessionsData?.sessions ?? [], [sessionsData]);

  // The selected session: the URL param when it names a live session, else the most-recent
  // one (list is recency-ordered), else none. Falling back this way self-heals a stale param
  // (e.g. the current session was just archived) without an extra effect.
  const selectedId = useMemo(() => {
    const param = params.get("session");
    if (param && sessions.some((s) => s.id === param)) return param;
    return sessions[0]?.id ?? null;
  }, [params, sessions]);

  const select = useCallback(
    (id: string) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("session", id);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const { data: messagesData } = useQuery({
    queryKey: ["messages", project.id, selectedId],
    queryFn: () => api.projectMessages(project.id, selectedId ?? undefined),
    enabled: selectedId != null,
  });
  const createSession = useMutation({
    mutationFn: () => sessionsApi.create(project.id),
    onSuccess: async (created) => {
      await qc.invalidateQueries({ queryKey: ["sessions", project.id] });
      select(created.id);
    },
  });

  const archiveSession = useMutation({
    mutationFn: (id: string) => sessionsApi.patch(project.id, id, { archived: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions", project.id] }),
  });

  // Guarantee a session before the first send: return the current one, or create (and select)
  // one. Lets the composer stay simple — it always sends into a concrete session.
  const ensureSession = useCallback(async (): Promise<string> => {
    if (selectedId) return selectedId;
    const created = await createSession.mutateAsync();
    return created.id;
  }, [selectedId, createSession]);

  const messages = messagesData?.messages ?? [];

  return (
    /* Full-height application workspace: fills the viewport below the shell
       header + project head (offsets: 48px header + 24px main pt + ~118px
       page-head + 24px breathing). The chat owns the height and scrolls
       internally. Mobile keeps natural flow. */
    /* -mb-16 swallows the shell's bottom padding so the document height lands
       exactly at the viewport: the window itself never scrolls on desktop. */
    /* One column since the rail went. The readable measure is NOT set here:
       PmChatPanel and PmComposer each already centre their own content at
       max-w-4xl, so the transcript centres while its scrollbar stays at the
       workspace edge rather than jumping inward. */
    <div className="flex flex-col gap-4 lg:-mb-16 lg:h-[calc(100dvh-88px)] lg:min-h-[460px]">
      <div className="flex min-h-0 min-w-0 flex-col lg:h-full">
        <PmSessionBar
          sessions={sessions}
          selectedId={selectedId}
          onSelect={select}
          onNew={() => createSession.mutate()}
          onArchive={(id) => archiveSession.mutate(id)}
          busy={createSession.isPending || archiveSession.isPending}
        />
        <div className="min-h-0 flex-1">
          <PmChatPanel
            project={project}
            messages={messages}
            sessionId={selectedId}
            ensureSession={ensureSession}
          />
        </div>
      </div>
    </div>
  );
}
