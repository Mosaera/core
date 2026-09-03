import { Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "../../api/client";

/** Expanded preview overlay for ANY attachment type: images at original
 *  resolution, PDFs in the browser's native viewer, text/code as a document
 *  pane. Click the backdrop (anywhere off the content) or press Escape to
 *  close. Text arrives as JSON and renders as text — uploaded HTML/JS is
 *  never executed. */
export function FilePreview({
  projectId,
  attachmentId,
  filename,
  mimeType,
  onClose,
}: {
  projectId: string;
  attachmentId: string;
  filename: string;
  mimeType: string;
  onClose: () => void;
}) {
  const isImage = mimeType.startsWith("image/");
  const isPdf = mimeType === "application/pdf";
  const [text, setText] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (isImage || isPdf) return;
    api
      .attachmentContent(projectId, attachmentId)
      .then((r) => {
        setText(r.text);
        setNote(r.note);
      })
      .catch(() => setError(true));
  }, [projectId, attachmentId, isImage, isPdf]);

  return createPortal(
    <div
      role="dialog"
      aria-label={`Preview: ${filename}`}
      onClick={onClose}
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-black/80 p-6 backdrop-blur-sm"
    >
      {isImage ? (
        <img
          src={api.attachmentImageUrl(projectId, attachmentId)}
          alt={filename}
          onClick={(e) => e.stopPropagation()}
          className="max-h-[82vh] max-w-[90vw] rounded-xl object-contain shadow-2xl"
        />
      ) : isPdf ? (
        <iframe
          src={api.attachmentFileUrl(projectId, attachmentId)}
          title={filename}
          onClick={(e) => e.stopPropagation()}
          className="h-[82vh] w-[min(90vw,64rem)] rounded-xl border-0 bg-white shadow-2xl"
        />
      ) : (
        <div
          onClick={(e) => e.stopPropagation()}
          className="flex max-h-[82vh] w-[min(90vw,52rem)] flex-col overflow-hidden rounded-xl border border-border bg-background shadow-2xl"
        >
          <div className="border-b border-border/60 px-4 py-2.5 font-mono text-xs text-muted-foreground">
            {filename}
          </div>
          {error ? (
            <p className="p-4 text-sm text-muted-foreground">Preview unavailable.</p>
          ) : text === null ? (
            <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading…
            </div>
          ) : (
            <>
              {note && <p className="px-4 pt-3 text-xs text-primary/80">{note}</p>}
              <pre className="overflow-auto whitespace-pre-wrap p-4 font-mono text-[12.5px] leading-relaxed">
                {text || "(empty file)"}
              </pre>
            </>
          )}
        </div>
      )}
      {isImage && (
        <span
          onClick={(e) => e.stopPropagation()}
          className="rounded-md bg-background/80 px-2.5 py-1 font-mono text-[11px] text-foreground backdrop-blur-sm"
        >
          {filename}
        </span>
      )}
      <button
        type="button"
        aria-label="Close preview"
        onClick={onClose}
        className="absolute right-4 top-4 cursor-pointer rounded-full border-0 bg-background/80 p-2 text-foreground shadow-none backdrop-blur-sm hover:bg-background"
      >
        <X className="size-4" />
      </button>
    </div>,
    document.body,
  );
}
