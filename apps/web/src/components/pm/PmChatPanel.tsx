import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown } from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import type { PmPrefillState } from "@/lib/backlog";
import {
  api,
  type ChangesetOp,
  type CharterProposal,
  type MessageAttachmentRef,
  type Project,
  type ProjectMessage,
} from "../../api/client";
import { CharterProposalCard } from "./CharterProposalCard";
import { PmChangesetCard } from "./PmChangesetCard";
import { PmComposer, type PmComposerHandle } from "./PmComposer";
import { PmTurnFailure } from "./PmTurnFailure";
import { PmWorking } from "./PmSteps";
import { sendMessageStreaming, type PmStep } from "@/api/pmStream";
import { PmMessage } from "./PmMessage";
import { PM_PROMPTS } from "./prompts";

/** The most recent OPEN proposal of `kind` in the transcript, with the message it belongs to.
 *
 *  Cards used to live only in the send response, so a refresh destroyed them — and because the
 *  agent strips the proposal out of the reply before it is stored, what survived was a bare
 *  "Here's what I'd suggest." with nothing under it. The server now stores proposals beside their
 *  turn, so the transcript can restore the card. Latest-only: an older superseded proposal is
 *  history, not a second thing to act on. */
function lastProposal(
  messages: ProjectMessage[],
  kind: "changeset" | "charter",
): { id: number; payload: unknown } | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const hit = (messages[i].proposals ?? []).find((p) => p.kind === kind);
    if (hit) return { id: hit.id, payload: hit.payload };
  }
  return null;
}

function fmtTime(at: string | null): string | undefined {
  if (!at) return undefined;
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toLocaleString();
}

function dayOf(at: string | null): string | null {
  if (!at) return null;
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? null : d.toDateString();
}

/** The PM conversation: identity header, readable transcript, inline proposals,
 *  premium composer. The chat owns the page; the rail only supports it. */
export function PmChatPanel({
  project,
  messages,
  sessionId,
  ensureSession,
}: {
  project: Project;
  messages: ProjectMessage[];
  /** The active session; null until the first send creates one. Omitted in the pre-backlog
   *  intake (StartWorkspace), which is a single conversation with no switcher. */
  sessionId?: string | null;
  /** Resolve/create the session to send into — keeps the composer session-agnostic. Omitted →
   *  send with no session id and let the server use the project's current session. */
  ensureSession?: () => Promise<string>;
}) {
  const qc = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const composerRef = useRef<PmComposerHandle>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const [pendingUser, setPendingUser] = useState<{
    text: string;
    attachments: MessageAttachmentRef[];
  } | null>(null);
  const [proposal, setProposal] = useState<{ key: number; ops: ChangesetOp[] } | null>(null);
  const [charterProposal, setCharterProposal] = useState<{
    key: number;
    proposal: CharterProposal;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The live turn: what he has looked up, what he has said on the way, and when it began. Cleared
  // when the persisted message arrives rather than on `done`, so the live block and the stored
  // reply never both vanish for a frame.
  const [liveSteps, setLiveSteps] = useState<PmStep[]>([]);
  const [liveProse, setLiveProse] = useState<string[]>([]);
  const [turnStartedAt, setTurnStartedAt] = useState(() => Date.now());
  // After a reload the send response is long gone; the turn's proposals come back WITH the
  // transcript, so the card is restored from there. Live state still wins for the turn that just
  // happened — it needs no round-trip and keeps the card mounted through follow-up sends.
  const storedChangeset = useMemo(() => lastProposal(messages, "changeset"), [messages]);
  const storedCharter = useMemo(() => lastProposal(messages, "charter"), [messages]);
  const activeChangeset = proposal
    ? { key: proposal.key, ops: proposal.ops, id: null as number | null }
    : storedChangeset
      ? { key: storedChangeset.id, ops: storedChangeset.payload as ChangesetOp[], id: storedChangeset.id }
      : null;
  const activeCharter = charterProposal
    ? { key: charterProposal.key, proposal: charterProposal.proposal, id: null as number | null }
    : storedCharter
      ? {
          key: storedCharter.id,
          proposal: storedCharter.payload as CharterProposal,
          id: storedCharter.id,
        }
      : null;
  // Recording the outcome is what stops a handled card returning on the next load. Best-effort:
  // it records what the operator DID and applies nothing, so a failure must not block them.
  const resolveStored = useCallback(
    (id: number | null, status: "accepted" | "dismissed") => {
      if (id == null) return;
      void api
        .resolveProposal(project.id, id, status)
        .catch(() => undefined)
        .finally(() => qc.invalidateQueries({ queryKey: ["messages", project.id] }));
    },
    [project.id, qc],
  );
  // The decision CARDS moved to the Overview's "Waiting on you" band (2026-08-22): in the
  // transcript they had no refetch interval, no dismissal and no acknowledgment, so they were
  // permanent furniture at the bottom of every conversation rather than notifications.
  //
  // This invalidation STAYS even though the chat renders nothing from it: a chat turn can resolve
  // a condition (Quincy raising a clarification, an operator applying a changeset), and the band
  // reads the same `["decisions", id]` key. Deleting it with the cards would have left the band
  // stale after exactly the turns most likely to change it — and nothing in the suite guards it,
  // so this comment is the guard.

  const send = useMutation({
    mutationFn: async ({
      text,
      attachments,
    }: {
      text: string;
      attachments: MessageAttachmentRef[];
    }) => {
      // Post into a concrete session — the current one, or one created on the first send.
      // No ensureSession (pre-backlog intake) → send with no id; the server uses the default.
      const sid = ensureSession ? await ensureSession() : undefined;
      return sendMessageStreaming(
        project.id,
        text,
        attachments.map((a) => a.id),
        sid,
        (event) => {
          // Only what he is doing and what he says on the way. The final reply never arrives
          // here — the transcript renders it, and showing it twice is the failure this avoids.
          if (event.event === "step") {
            setLiveSteps((s) => [
              ...s,
              { kind: "tool", tool: event.data.kind, arg: event.data.detail },
            ]);
          } else if (event.event === "text") {
            setLiveProse((p) => [...p, event.data.text]);
          }
        },
      );
    },
    onMutate: ({ text, attachments }) => {
      setError(null);
      setPendingUser({ text, attachments });
      setLiveSteps([]);
      setLiveProse([]);
      setTurnStartedAt(Date.now());
    },
    onSuccess: (r) => {
      if (r.changeset?.length) setProposal({ key: Date.now(), ops: r.changeset });
      if (r.charter_proposal) setCharterProposal({ key: Date.now(), proposal: r.charter_proposal });
      // Quincy raised (and the server STORED) an intake clarification on an item — refresh
      // the project so the board's "Question open" badge and the item sheet's clarify card
      // appear without a reload (ADR-0080 §1).
      if (r.clarified_item) qc.invalidateQueries({ queryKey: ["project", project.id] });
      // Prefix key: refreshes the active session's transcript; sessions list refreshes for
      // the recency re-order + first-turn auto-title.
      qc.invalidateQueries({ queryKey: ["messages", project.id] });
      qc.invalidateQueries({ queryKey: ["sessions", project.id] });
      qc.invalidateQueries({ queryKey: ["decisions", project.id] });
    },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
    onSettled: () => setPendingUser(null),
  });

  // Backlog → PM handoff: a prefill riding on router state populates the
  // composer (fills + focuses, never sends). Consumed once on mount, then the
  // state is stripped so back-nav or a remount can't re-populate.
  useEffect(() => {
    const prefill = (location.state as PmPrefillState | null)?.pmPrefill;
    if (!prefill) return;
    composerRef.current?.populate(prefill);
    navigate(location.pathname, { replace: true, state: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Switching threads clears thread-local UI: a changeset proposal or error from one session
  // must not bleed into another (the transcript itself swaps via the messages prop).
  useEffect(() => {
    setProposal(null);
    setCharterProposal(null);
    setError(null);
  }, [sessionId]);

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    setShowJump(false);
  }, []);

  // Follow the conversation only while the user is at the bottom; if they've
  // scrolled up, don't yank — offer a "Jump to latest" affordance instead.
  useEffect(() => {
    if (atBottomRef.current) scrollToBottom();
    else setShowJump(true);
  }, [messages.length, pendingUser, proposal, scrollToBottom]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    atBottomRef.current = atBottom;
    if (atBottom) setShowJump(false);
  }

  const empty = messages.length === 0 && !pendingUser;

  return (
    /* Native chat surface: no card, no header — the transcript scrolls on the
       page itself and the composer is the only strongly defined object. PM
       identity comes from the avatar on messages; the breadcrumb carries the
       project; the rail owns the waiting/context signals. */
    <div
      data-slot="pm-chat-panel"
      className="flex h-[min(700px,calc(100dvh-170px))] min-h-0 flex-col lg:h-full"
    >

      {/* Transcript — readable measure, centered in the panel */}
      <div className="relative min-h-0 flex-1">
        {/* Invisible scrollbar: the transcript scrolls, but no bar competes
            with the conversation (Firefox + Chromium via scrollbar-width,
            WebKit via the pseudo-element). */}
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="h-full overflow-y-auto px-4 py-5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
            {empty ? (
              <div className="flex min-h-[360px] flex-col items-center justify-center gap-5 text-center">
                <div>
                  <p className="text-lg font-semibold tracking-tight">
                    What should we work on next?
                  </p>
                  <p className="mx-auto mt-1.5 max-w-md text-[13px] leading-relaxed text-muted-foreground">
                    The PM can plan work, prioritize the backlog, prepare runs, review
                    outputs, and turn your feedback into project changes.
                  </p>
                </div>
                <div className="flex max-w-lg flex-wrap justify-center gap-1.5">
                  {PM_PROMPTS.map((p) => (
                    <Button
                      key={p.label}
                      size="sm"
                      variant="outline"
                      className="h-7 rounded-full px-3 font-mono text-[11px] text-muted-foreground hover:text-foreground"
                      onClick={() => composerRef.current?.populate(p.prompt)}
                    >
                      {p.label}
                    </Button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                {messages.map((m, i) => {
                  const day = dayOf(m.created_at);
                  const prevDay = i > 0 ? dayOf(messages[i - 1].created_at) : null;
                  return (
                    <Fragment key={i}>
                      {day && day !== prevDay && (
                        <PmMessage variant="system">{day}</PmMessage>
                      )}
                      {/* A failure note is neither party's words. Without this branch the old
                          ternary's `else` rendered it as a right-aligned USER bubble — the failure
                          appearing as something the operator had said. */}
                      {m.role === "note" ? (
                        <PmTurnFailure cause={m.content} timestamp={fmtTime(m.created_at)} />
                      ) : (
                      <PmMessage
                        variant={m.role === "pm" ? "pm" : "user"}
                        timestamp={fmtTime(m.created_at)}
                        copyText={m.role === "pm" ? m.content : undefined}
                        attachments={m.attachments}
                        contextSources={m.role === "pm" ? m.context_sources : undefined}
                        steps={m.role === "pm" ? m.steps : undefined}
                        projectId={project.id}
                      >
                        {m.content}
                      </PmMessage>
                      )}
                    </Fragment>
                  );
                })}
                {/* Card stays mounted through follow-up sends (guardrails 2+3). */}
                {activeChangeset && (
                  <PmChangesetCard
                    key={activeChangeset.key}
                    projectId={project.id}
                    ops={activeChangeset.ops}
                    items={project.backlog ?? []}
                    onSend={(t) => send.mutate({ text: t, attachments: [] })}
                    sendBusy={send.isPending}
                    onResolved={(status) => resolveStored(activeChangeset.id, status)}
                  />
                )}
                {activeCharter && (
                  <CharterProposalCard
                    key={activeCharter.key}
                    projectId={project.id}
                    proposal={activeCharter.proposal}
                    onDecline={(r) => {
                      resolveStored(activeCharter.id, "dismissed");
                      send.mutate({ text: `Declining the charter: ${r}.`, attachments: [] });
                    }}
                    onResolved={(status) => resolveStored(activeCharter.id, status)}
                  />
                )}
                {pendingUser && (
                  <>
                    {/* Optimistic echo keeps the attachment chips visible too. */}
                    <PmMessage
                      variant="user"
                      attachments={pendingUser.attachments}
                      projectId={project.id}
                    >
                      {pendingUser.text}
                    </PmMessage>
                    <PmWorking steps={liveSteps} prose={liveProse} startedAt={turnStartedAt} />
                  </>
                )}
                {error && (
                  <p role="alert" className="text-xs text-destructive">
                    {error}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
        {showJump && (
          <Button
            size="sm"
            variant="outline"
            onClick={scrollToBottom}
            className="absolute bottom-3 left-1/2 h-7 -translate-x-1/2 rounded-full border-primary/40 bg-background px-3 font-mono text-[11px] text-primary shadow-md hover:bg-primary/10"
          >
            <ArrowDown className="size-3.5" /> Jump to latest
          </Button>
        )}
      </div>

      <PmComposer
        ref={composerRef}
        projectId={project.id}
        onSend={(t, attachments) => send.mutate({ text: t, attachments })}
        busy={send.isPending}
      />
    </div>
  );
}
