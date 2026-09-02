import { BookOpenCheck, FileText } from "lucide-react";

import { CopyButton } from "@/components/ui/CopyButton";
import { useState } from "react";

import { cn } from "@/lib/utils";

import pmAvatar from "../../assets/quincy-avatar.png";
import pmPortrait from "../../assets/quincy-portrait.png";
import { api, type MessageAttachmentRef, type MessageContextSource } from "../../api/client";
import { FilePreview } from "./FilePreview";
import { ImageLightbox } from "./ImageLightbox";
import { PmMarkdown } from "./PmMarkdown";
import { PmStepsSummary } from "./PmSteps";
import type { PmStep } from "@/api/pmStream";

/** Canonical receipt wording — one vocabulary for the visible line AND the
 *  tooltips, mirroring the builder's inclusion modes exactly. */
const INCLUDED_AS_LABEL: Record<string, string> = {
  included_raw: "read in full",
  truncated: "truncated",
  chunks: "excerpts",
  summary: "summary",
  reference_only: "referenced only",
};

/** Quiet "Used" line under a PM reply — recorded by the prompt builder when
 *  the reply was generated, never inferred after the fact. Brief/backlog ride
 *  along on EVERY turn, so listing them each time is noise: the line renders
 *  only when files were involved, with the always-on sources in the tooltip. */
function UsedContext({ sources }: { sources: MessageContextSource[] }) {
  const files = sources.filter((s) => s.source_type === "attachment");
  if (files.length === 0) return null;
  const always = sources
    .filter((s) => s.source_type !== "attachment")
    .map((s) => s.title)
    .join(", ");
  return (
    <p
      className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 font-mono text-[10px] text-muted-foreground/50"
      title={always ? `Also used: ${always}` : undefined}
    >
      <span className="uppercase tracking-wide">Used:</span>
      {files.map((s, i) => (
        <span
          key={i}
          className="max-w-44 truncate"
          title={`${s.title} — ${INCLUDED_AS_LABEL[s.included_as] ?? s.included_as}`}
        >
          {s.title}
          <span className="text-primary/60">
            {" "}
            ({INCLUDED_AS_LABEL[s.included_as] ?? s.included_as})
          </span>
          {i < files.length - 1 ? " ·" : ""}
        </span>
      ))}
    </p>
  );
}

/* Message-type visual system. Only user/pm exist in history today; the system
   variant is structural, ready for project events when the backend emits them. */
export type PmMessageVariant = "user" | "pm" | "system";

function fmtBytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

/** Files that rode on a message stay visible in the transcript — an attachment
 *  must never feel like it disappeared after send. Shown ABOVE the bubble as a
 *  readable file card: icon tile, name + size stacked to match the tile's
 *  height, and a project-context indicator on the right when promoted. */
function MessageAttachments({
  attachments,
  projectId,
}: {
  attachments: MessageAttachmentRef[];
  projectId?: string;
}) {
  const [expanded, setExpanded] = useState<MessageAttachmentRef | null>(null);
  if (attachments.length === 0) return null;
  return (
    <div className="mb-1.5 flex flex-wrap justify-end gap-2">
      {expanded && projectId && (
        <FilePreview
          projectId={projectId}
          attachmentId={expanded.id}
          filename={expanded.filename}
          mimeType={expanded.mime_type ?? "text/plain"}
          onClose={() => setExpanded(null)}
        />
      )}
      {attachments.map((a) =>
        projectId && a.mime_type?.startsWith("image/") ? (
          // Images are image-first: a big square thumbnail of the actual
          // picture, filename as alt text, context badge overlaid. Click
          // expands the original in an overlay; the backdrop closes it.
          <button
            key={a.id}
            type="button"
            aria-label={`Expand ${a.filename}`}
            onClick={() => setExpanded(a)}
            className="relative block cursor-zoom-in overflow-hidden rounded-xl border border-border/50 bg-transparent p-0 shadow-none"
            title={
              a.scope === "project_context"
                ? `${a.filename} — in project context: the PM sees this file in every conversation`
                : a.filename
            }
          >
            <img
              src={api.attachmentThumbnailUrl(projectId, a.id)}
              alt={a.filename}
              className="size-28 bg-muted/60 object-cover"
            />
            <span className="absolute inset-x-0 bottom-0 truncate bg-background/75 px-2 py-1 text-left text-[10px] text-foreground backdrop-blur-sm">
              {a.filename}
            </span>
            {a.scope === "project_context" && (
              <span className="absolute right-1 top-1 flex items-center gap-1 rounded-md bg-background/80 px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-wide text-primary backdrop-blur-sm">
                <BookOpenCheck className="size-3" /> Context
              </span>
            )}
          </button>
        ) : (
        // File cards expand too: click opens the document preview overlay.
        <button
          key={a.id}
          type="button"
          aria-label={`Expand ${a.filename}`}
          onClick={() => projectId && setExpanded(a)}
          className="flex cursor-pointer items-center gap-2.5 rounded-xl border border-border/50 bg-background py-2 pl-2 pr-3 text-left shadow-none transition-colors hover:bg-muted/30"
          title={
            a.scope === "project_context"
              ? `${a.filename} — in project context: the PM sees this file in every conversation`
              : a.filename
          }
        >
          <span className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted/60 text-muted-foreground">
            <FileText className="size-4.5" />
          </span>
          <span className="flex min-w-0 flex-col justify-center leading-tight">
            <span className="max-w-52 truncate text-[13px] font-medium text-foreground">
              {a.filename}
            </span>
            <span className="text-[11px] text-muted-foreground">{fmtBytes(a.size_bytes)}</span>
          </span>
          {a.scope === "project_context" && (
            <span className="ml-1 flex items-center gap-1 border-l border-border/50 pl-2.5 text-primary/80">
              <BookOpenCheck className="size-3.5 shrink-0" />
              {/* width-constrained so it stacks into two lines matching the tile height */}
              <span className="w-12 font-mono text-[9px] uppercase leading-tight tracking-wide">
                Project context
              </span>
            </span>
          )}
        </button>
        ),
      )}
    </div>
  );
}

/** The PM's display name — Quincy, the orchestrator. */
export const PM_NAME = "Quincy";

export function PmAvatar() {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      {expanded && (
        <ImageLightbox
          src={pmPortrait}
          alt={`${PM_NAME} — Project Manager`}
          onClose={() => setExpanded(false)}
        />
      )}
      {/* Click to view the full portrait (same overlay as image attachments). */}
      <button
        type="button"
        aria-label={`View ${PM_NAME}'s profile picture`}
        onClick={() => setExpanded(true)}
        className="shrink-0 cursor-zoom-in border-0 bg-transparent p-0 shadow-none"
      >
        <img
          src={pmAvatar}
          alt="" // decorative — the name row identifies the PM
          className="size-[52px] select-none rounded-full object-cover"
        />
      </button>
    </>
  );
}

export function PmMessage({
  variant,
  children,
  timestamp,
  copyText,
  attachments = [],
  contextSources = [],
  steps,
  projectId,
}: {
  variant: PmMessageVariant;
  children: React.ReactNode;
  /** human-readable time shown as a native tooltip */
  timestamp?: string;
  /** enables the hover copy action (PM messages) */
  copyText?: string;
  /** files that rode on this message (user turns) */
  attachments?: MessageAttachmentRef[];
  /** context the PM reply used (4D traceability chips) */
  contextSources?: MessageContextSource[];
  /** What this turn looked up before answering (slice 4); absent on older rows. */
  steps?: PmStep[];
  /** enables image thumbnails on the file cards */
  projectId?: string;
}) {
  if (variant === "system") {
    return (
      <div className="flex justify-center py-0.5">
        <span className="font-mono text-[11px] text-muted-foreground/60">{children}</span>
      </div>
    );
  }
  if (variant === "user") {
    // Attachment-only sends are valid — skip the empty bubble entirely.
    const hasText = typeof children === "string" ? children.trim().length > 0 : Boolean(children);
    return (
      <div className="flex flex-col items-end">
        <MessageAttachments attachments={attachments} projectId={projectId} />
        {hasText && (
          <div
            title={timestamp}
            className="max-w-[78%] whitespace-pre-line rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-base leading-relaxed"
          >
            {children}
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="group flex items-start gap-3" title={timestamp}>
      <PmAvatar />
      <div className="min-w-0 max-w-[92%] flex-1 text-base leading-relaxed">
        {/* Messaging-app name row: who's speaking, at a glance. */}
        <div className="mb-0.5 flex items-baseline gap-1.5">
          <span className="text-sm font-semibold text-primary">{PM_NAME}</span>
          <span className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground/60">
            PM
          </span>
        </div>
        {/* PM replies are markdown (bold, lists, tables); copy keeps the raw text. */}
        {typeof children === "string" ? <PmMarkdown>{children}</PmMarkdown> : children}
        <UsedContext sources={contextSources} />
        {/* What he looked up before writing this, folded away. Same component the
            live block used, fed from the stored rows — so a reload shows the same
            thing the operator watched happen. */}
        {steps?.length ? <PmStepsSummary steps={steps} /> : null}
      </div>
      {copyText && (
        <CopyButton
          text={copyText}
          label="Copy message"
          copiedLabel="Copied"
          className={cn(
            "mt-0.5 size-auto rounded-md p-1 text-muted-foreground/50 opacity-0 transition-opacity",
            "hover:bg-muted focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            "group-hover:opacity-100",
          )}
        />
      )}
    </div>
  );
}

/** Blocking-send indicator (no streaming endpoint exists yet). */
export function PmThinking() {
  return (
    <div className="flex items-center gap-2.5" aria-live="polite">
      <PmAvatar />
      <div className="flex items-center gap-2">
        <span className="flex items-center gap-1" aria-hidden>
          <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground/60 [animation-delay:0ms]" />
          <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground/60 [animation-delay:150ms]" />
          <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground/60 [animation-delay:300ms]" />
        </span>
        <span className="font-mono text-[11px] text-muted-foreground/70">
          {PM_NAME} is thinking…
        </span>
      </div>
    </div>
  );
}
