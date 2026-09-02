import { FileText, Loader2, Mic, Paperclip, SendHorizonal, X } from "lucide-react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { api, type AttachmentScope, type MessageAttachmentRef } from "../../api/client";
import { FilePreview } from "./FilePreview";
import { ImageLightbox } from "./ImageLightbox";
import { useVoiceInput } from "./useVoiceInput";
import { VoiceWaveform } from "./VoiceWaveform";

export interface PmComposerHandle {
  /** Fill the composer (from a starter chip) and focus it — no auto-send. */
  populate: (text: string) => void;
}

/** In-dock upload chip. Client checks are UX only — the server re-validates
 *  everything and is authoritative. Processing runs server-side in the
 *  background; the chip polls until ready/failed (bounded, guardrail 12). */
interface ComposerAttachment {
  localId: string;
  id?: string; // server id once uploaded
  fileName: string;
  sizeBytes: number;
  mimeType: string;
  scope: AttachmentScope;
  status: "uploading" | "processing" | "ready" | "failed";
  error?: string;
  large?: boolean;
  startedAt: number;
  /** local object URL for instant image preview (revoked on removal/send) */
  previewUrl?: string;
}

const ACCEPT =
  ".md,.txt,.json,.yaml,.yml,.csv,.ts,.tsx,.js,.jsx,.py,.go,.rs,.html,.css,.pdf,.png,.jpg,.jpeg,.webp";
const MAX_PER_MESSAGE = 5;
const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 90_000;

/** UX pre-check limits per type (the server re-validates authoritatively). */
function sizeLimit(name: string): { max: number; label: string } {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  if (ext === "pdf") return { max: 20 * 1024 * 1024, label: "20 MB" };
  if (["png", "jpg", "jpeg", "webp"].includes(ext)) return { max: 10 * 1024 * 1024, label: "10 MB" };
  return { max: 2 * 1024 * 1024, label: "2 MB" };
}

const SCOPE_LABEL: Record<AttachmentScope, string> = {
  message_only: "This message",
  project_context: "Project context",
};

function AttachmentChip({
  projectId,
  att,
  onRemove,
  onToggleScope,
}: {
  projectId: string;
  att: ComposerAttachment;
  onRemove: () => void;
  onToggleScope: () => void;
}) {
  const busy = att.status === "uploading" || att.status === "processing";
  const [expanded, setExpanded] = useState(false);
  // Images are image-first: a big square preview of the actual picture
  // (local object URL instantly, matching the transcript's treatment).
  // Click expands the overlay; the backdrop closes it.
  if (att.mimeType.startsWith("image/") && att.status !== "failed" && att.previewUrl) {
    const fullSrc =
      att.status === "ready" && att.id
        ? api.attachmentImageUrl(projectId, att.id)
        : att.previewUrl;
    return (
      <span
        className="relative block overflow-hidden rounded-xl border border-border/60"
        title={att.fileName}
      >
        {expanded &&
          (att.status === "ready" && att.id ? (
            <FilePreview
              projectId={projectId}
              attachmentId={att.id}
              filename={att.fileName}
              mimeType={att.mimeType}
              onClose={() => setExpanded(false)}
            />
          ) : (
            <ImageLightbox src={fullSrc} alt={att.fileName} onClose={() => setExpanded(false)} />
          ))}
        <img
          src={
            att.status === "ready" && att.id
              ? api.attachmentThumbnailUrl(projectId, att.id)
              : att.previewUrl
          }
          alt={att.fileName}
          onClick={() => !busy && setExpanded(true)}
          className={cn(
            "size-24 cursor-zoom-in bg-muted/60 object-cover",
            busy && "cursor-default opacity-50",
          )}
        />
        {busy && (
          <span className="absolute inset-0 flex items-center justify-center">
            <Loader2 className="size-5 animate-spin text-foreground" />
          </span>
        )}
        <span className="absolute inset-x-0 bottom-0 truncate bg-background/75 px-1.5 py-0.5 text-[9px] text-foreground backdrop-blur-sm">
          {att.fileName}
        </span>
        {att.status === "ready" && (
          <button
            type="button"
            onClick={onToggleScope}
            aria-label={`Scope for ${att.fileName}: ${SCOPE_LABEL[att.scope]} (click to change)`}
            className={cn(
              "absolute left-1 top-1 cursor-pointer rounded-md border-0 px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-wide shadow-none backdrop-blur-sm transition-colors",
              att.scope === "project_context"
                ? "bg-primary/80 text-primary-foreground"
                : "bg-background/80 text-muted-foreground hover:text-foreground",
            )}
          >
            {att.scope === "project_context" ? "Context" : "Message"}
          </button>
        )}
        <button
          type="button"
          aria-label={`Remove ${att.fileName}`}
          onClick={onRemove}
          className="absolute right-1 top-1 cursor-pointer rounded-full border-0 bg-background/80 p-1 text-foreground shadow-none backdrop-blur-sm hover:bg-background"
        >
          <X className="size-3" />
        </button>
      </span>
    );
  }
  return (
    <span
      className={cn(
        "flex items-center gap-1.5 rounded-md border border-border/60 bg-muted/40 py-1 pl-2 pr-1 text-xs",
        att.status === "failed" && "border-destructive/40 text-destructive",
      )}
    >
      {expanded && att.id && (
        <FilePreview
          projectId={projectId}
          attachmentId={att.id}
          filename={att.fileName}
          mimeType={att.mimeType}
          onClose={() => setExpanded(false)}
        />
      )}
      {busy ? (
        <Loader2 className="size-3 animate-spin text-muted-foreground" />
      ) : (
        <FileText className="size-3 shrink-0 text-muted-foreground" />
      )}
      {/* Ready files expand to the document preview on click. */}
      <button
        type="button"
        onClick={() => att.status === "ready" && att.id && setExpanded(true)}
        aria-label={att.status === "ready" ? `Expand ${att.fileName}` : att.fileName}
        className={cn(
          "max-w-40 cursor-pointer truncate border-0 bg-transparent p-0 text-left shadow-none",
          att.status === "ready" && "hover:underline",
        )}
        title={att.fileName}
      >
        {att.fileName}
      </button>
      {att.status === "processing" && (
        <span className="font-mono text-[9px] uppercase tracking-wide text-muted-foreground/70">
          Processing…
        </span>
      )}
      {att.status === "ready" && (
        <button
          type="button"
          onClick={onToggleScope}
          aria-label={`Scope for ${att.fileName}: ${SCOPE_LABEL[att.scope]} (click to change)`}
          className={cn(
            "cursor-pointer rounded-sm border-0 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide shadow-none transition-colors",
            att.scope === "project_context"
              ? "bg-primary/15 text-primary"
              : "bg-secondary text-muted-foreground hover:text-foreground",
          )}
        >
          {SCOPE_LABEL[att.scope]}
        </button>
      )}
      {att.status === "failed" && att.error && (
        <span role="alert" className="max-w-48 truncate text-[10px]" title={att.error}>
          {att.error}
        </span>
      )}
      <button
        type="button"
        aria-label={`Remove ${att.fileName}`}
        onClick={onRemove}
        className="cursor-pointer rounded border-0 bg-transparent p-0.5 text-muted-foreground/60 shadow-none hover:bg-muted hover:text-foreground"
      >
        <X className="size-3" />
      </button>
    </span>
  );
}

/** ONE calm input dock: upload chips (top, when present), textarea, then a
 *  single control row — attach left, mic + send right. */
export const PmComposer = forwardRef<
  PmComposerHandle,
  {
    projectId: string;
    /** refs carry filename+scope so the optimistic echo can show the chips */
    onSend: (text: string, attachments: MessageAttachmentRef[]) => void;
    busy: boolean;
  }
>(function PmComposer({ projectId, onSend, busy }, ref) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Voice dictation: accepted text appends to the composer (never auto-sent);
  // browser-route interim text previews live after the accepted base.
  const voiceBaseRef = useRef("");
  const joinText = (a: string, b: string) => (a && b ? `${a.trimEnd()} ${b}` : a || b);
  const voice = useVoiceInput({
    onInterim: (interim) => setText(joinText(voiceBaseRef.current, interim)),
    onFinal: (final) => {
      voiceBaseRef.current = joinText(voiceBaseRef.current, final);
      setText(voiceBaseRef.current);
      taRef.current?.focus();
    },
  });

  function startVoice() {
    voiceBaseRef.current = text;
    voice.start();
  }

  // Escape during a recording cancels it cleanly (guardrail 4).
  useEffect(() => {
    if (voice.state !== "recording") return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setText(voiceBaseRef.current); // drop unaccepted interim text only
        voice.cancel();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voice.state]);

  // Auto-grow: the textarea expands with content up to ~15 lines, then
  // scrolls internally. The composer stays anchored; the page never scrolls.
  const MAX_TA_PX = 15 * 26 + 20; // 15 lines at text-base/relaxed + padding
  const autoGrow = useCallback(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const target = Math.min(ta.scrollHeight, MAX_TA_PX);
    if (target > 0) ta.style.height = `${target}px`;
    ta.style.overflowY = ta.scrollHeight > MAX_TA_PX ? "auto" : "hidden";
  }, [MAX_TA_PX]);

  useEffect(() => {
    autoGrow();
  }, [text, autoGrow]);

  useImperativeHandle(ref, () => ({
    populate: (t: string) => {
      setText(t);
      // F73 (#96): a prefill is a SENTENCE STEM the operator finishes — `Regarding the backlog
      // item "X": `. Focusing alone left the caret wherever the browser put it, and clicking into
      // the box (the natural habit) drops it at the click point, splicing the operator's message
      // into the middle of the stem. Driving LedgerCLI through the UI, the very first message to
      // the PM came out as `…pipe-delimitethis item wants the list command…` (case study #2,
      // 2026-08-23). Park the caret at the end, after the value has actually landed.
      requestAnimationFrame(() => {
        const ta = taRef.current;
        if (!ta) return;
        ta.focus();
        ta.setSelectionRange(ta.value.length, ta.value.length);
        ta.scrollTop = ta.scrollHeight;
      });
    },
  }));

  function patch(localId: string, patchData: Partial<ComposerAttachment>) {
    setAttachments((prev) =>
      prev.map((a) => (a.localId === localId ? { ...a, ...patchData } : a)),
    );
  }

  // Bounded polling while any chip is processing (guardrail 12): 1.5s ticks,
  // stops when everything settles or on unmount, times out with honest copy.
  const hasProcessing = attachments.some((a) => a.status === "processing" && a.id);
  useEffect(() => {
    if (!hasProcessing) return;
    const timer = setInterval(() => {
      setAttachments((prev) => prev); // read the latest list below
      for (const att of attachments) {
        if (att.status !== "processing" || !att.id) continue;
        if (Date.now() - att.startedAt > POLL_TIMEOUT_MS) {
          patch(att.localId, {
            status: "failed",
            error: "Processing is taking too long — remove and try again",
          });
          continue;
        }
        void api
          .getAttachment(projectId, att.id)
          .then((server) => {
            if (server.status === "ready") {
              patch(att.localId, { status: "ready", large: server.large });
            } else if (server.status === "failed") {
              patch(att.localId, {
                status: "failed",
                error: server.error_message || "Processing failed",
              });
            }
          })
          .catch(() => {});
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasProcessing, attachments, projectId]);

  async function onFiles(files: FileList | null) {
    if (!files) return;
    const room = MAX_PER_MESSAGE - attachments.length;
    for (const file of Array.from(files).slice(0, Math.max(room, 0))) {
      const localId = `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const base = {
        localId,
        fileName: file.name,
        sizeBytes: file.size,
        mimeType: file.type,
        scope: "message_only" as AttachmentScope,
        startedAt: Date.now(),
        // Instant local preview for images (the real file, not a claim).
        previewUrl: file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined,
      };
      // UX-only pre-check; the server is authoritative and re-validates.
      const limit = sizeLimit(file.name);
      if (file.size > limit.max) {
        setAttachments((prev) => [
          ...prev,
          { ...base, status: "failed", error: `File too large (limit ${limit.label})` },
        ]);
        continue;
      }
      setAttachments((prev) => [...prev, { ...base, status: "uploading" }]);
      try {
        const uploaded = await api.uploadAttachment(projectId, file, "message_only");
        patch(localId, {
          id: uploaded.id,
          fileName: uploaded.filename,
          mimeType: uploaded.mime_type,
          large: uploaded.large,
          startedAt: Date.now(),
          // Server processes in the background; the chip polls to ready.
          status: uploaded.status === "ready" ? "ready" : "processing",
        });
      } catch (e) {
        patch(localId, {
          status: "failed",
          error: e instanceof Error ? e.message.replace(/^\d+ [^:]+: ?/, "") : String(e),
        });
      }
    }
    if (fileRef.current) fileRef.current.value = "";
  }

  async function toggleScope(att: ComposerAttachment) {
    if (!att.id || busy) return;
    const next: AttachmentScope =
      att.scope === "message_only" ? "project_context" : "message_only";
    try {
      const updated = await api.patchAttachmentScope(projectId, att.id, next);
      patch(att.localId, { scope: updated.scope });
    } catch (e) {
      patch(att.localId, {
        status: "failed",
        error: e instanceof Error ? e.message.replace(/^\d+ [^:]+: ?/, "") : String(e),
      });
    }
  }

  function removeAttachment(att: ComposerAttachment) {
    if (att.previewUrl) URL.revokeObjectURL(att.previewUrl);
    setAttachments((prev) => prev.filter((a) => a.localId !== att.localId));
    if (att.id) {
      // Composer removal soft-deletes the upload server-side, then refreshes
      // the rail so the file disappears from PM Context immediately.
      void api.deleteAttachment(projectId, att.id).catch(() => {});
    }
  }

  function send() {
    const t = text.trim();
    if (busy) return;
    if (attachments.some((a) => a.status === "uploading" || a.status === "processing")) return;
    const refs = attachments
      .filter((a): a is ComposerAttachment & { id: string } => a.status === "ready" && !!a.id)
      .map((a) => ({
        id: a.id,
        filename: a.fileName,
        scope: a.scope,
        size_bytes: a.sizeBytes,
        mime_type: a.mimeType,
      }));
    // A file alone is a valid message ("here's the doc you asked for") —
    // only a completely empty send is blocked.
    if (!t && refs.length === 0) return;
    for (const a of attachments) if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
    onSend(t, refs);
    setText("");
    setAttachments([]);
  }

  const hasReady = attachments.some((a) => a.status === "ready");
  const stillWorking = attachments.some(
    (a) => a.status === "uploading" || a.status === "processing",
  );
  const hasLarge = attachments.some((a) => a.status === "ready" && a.large);

  return (
    /* Aligned with the conversation column: the dock shares the transcript's
       readable measure instead of stretching across the page. */
    <div className="mx-auto flex w-full max-w-4xl flex-col px-3 pb-3 pt-1.5 lg:px-0">
      {/* No focus ring or amber glow — the text cursor is the focus indicator;
          only the border brightens a touch. Send stays the sole amber element. */}
      <div
        className={cn(
          "rounded-2xl border border-input bg-background/80 transition-colors",
          "focus-within:border-foreground/25",
        )}
      >
        {voice.state === "recording" ? (
          /* Recording takes over the dock — no other input while dictating.
             The live preview keeps browser-route words visible; typed text is
             preserved and returns with the textarea when recording ends. */
          <div className="flex flex-col gap-2 px-3.5 pb-3 pt-3.5" role="status">
            <span className="sr-only">Recording…</span>
            <VoiceWaveform analyser={voice.analyser} wide />
            <p className="min-h-5 truncate text-sm text-muted-foreground">
              {text.trim() ? text : "Listening…"}
            </p>
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1.5 font-mono text-[11px] tabular-nums text-destructive">
                <span className="size-2 animate-pulse rounded-full bg-destructive" aria-hidden />
                {Math.floor(voice.seconds / 60)}:{String(voice.seconds % 60).padStart(2, "0")}
              </span>
              <span className="flex-1" />
              <span className="font-mono text-[10px] text-muted-foreground/60">
                Esc to cancel
              </span>
              <Button
                size="sm"
                variant="outline"
                className="h-7 rounded-lg px-2.5 font-mono text-[11px]"
                aria-label="Stop recording and transcribe"
                onClick={voice.stop}
              >
                Stop
              </Button>
            </div>
          </div>
        ) : (
          <>
        {attachments.length > 0 && (
          <div className="flex flex-col gap-1 px-3 pt-2.5">
            <div className="flex flex-wrap gap-1.5">
              {attachments.map((att) => (
                <AttachmentChip
                  key={att.localId}
                  projectId={projectId}
                  att={att}
                  onRemove={() => removeAttachment(att)}
                  onToggleScope={() => toggleScope(att)}
                />
              ))}
            </div>
            {hasLarge && (
              // Guardrail 14: be honest that big files aren't injected raw.
              <p className="text-[11px] text-muted-foreground/70">
                Large file. The PM will use a summary and relevant excerpts.
              </p>
            )}
          </div>
        )}
        <textarea
          ref={taRef}
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Ask the PM to plan, prioritize, review, or prepare the next run…"
          /* border-0/shadow-none/font-sans neutralize the legacy global
             textarea rules (inner border + amber :focus glow + mono font).
             Height is managed by autoGrow (15-line cap, then internal scroll). */
          className="min-h-[3.5rem] w-full resize-none border-0 bg-transparent px-3.5 pb-1.5 pt-3.5 font-sans text-base leading-relaxed shadow-none outline-none [scrollbar-width:thin] placeholder:text-muted-foreground/60"
        />
        {voice.notice && (
          // Calm, actionable copy — never raw library errors (guardrail 12).
          <p role="alert" className="px-3.5 pb-1 text-[11px] text-muted-foreground">
            {voice.notice}
          </p>
        )}
        <div className="flex items-center gap-1 px-2.5 pb-2.5">
          <input
            ref={fileRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            aria-hidden
            tabIndex={-1}
            onChange={(e) => onFiles(e.target.files)}
          />
          <Button
            size="icon"
            variant="ghost"
            className="size-7 rounded-lg text-muted-foreground/60 hover:text-foreground"
            aria-label="Attach files"
            title="Attach text, code, PDF, or image files"
            onClick={() => fileRef.current?.click()}
            disabled={busy || attachments.length >= MAX_PER_MESSAGE}
          >
            <Paperclip className="size-4" />
          </Button>

          <div className="flex-1" />

          {/* Voice lives inside the dock (guardrail 13); recording itself
              takes the whole dock over (branch above). */}
          {voice.state === "transcribing" ? (
            <span className="flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" />
              {voice.preparing
                ? "Voice model is being prepared. This can take a few minutes the first time."
                : "Transcribing…"}
            </span>
          ) : (
            <Button
              size="icon"
              variant="ghost"
              className="size-7 rounded-lg text-muted-foreground/60 hover:text-foreground"
              aria-label={voice.available ? "Start voice input" : "Voice input unavailable"}
              title={voice.tooltip}
              onClick={startVoice}
              disabled={!voice.available || busy}
            >
              <Mic className="size-4" />
            </Button>
          )}
          <Button
            size="icon"
            aria-label="Send message to the PM"
            title={stillWorking ? "Processing attachment…" : undefined}
            className="size-8 rounded-xl"
            onClick={send}
            disabled={
              busy ||
              (!text.trim() && !hasReady) ||
              stillWorking ||
              voice.state === "transcribing"
            }
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : <SendHorizonal className="size-4" />}
          </Button>
        </div>
          </>
        )}
      </div>
    </div>
  );
});
