import { Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "../../api/client";
import { clipPreview, previewKind } from "../../lib/artifacts";

/** Preview overlay for a produced project file — the deliverables sibling of
 *  the PM attachment FilePreview (same learned interaction: Escape or backdrop
 *  to close). Text is fetched and rendered as text in a <pre> — produced
 *  HTML/JS is never executed; svg only ever renders via <img>. */
export function ProjectFilePreview({
  projectId,
  path,
  onClose,
}: {
  projectId: string;
  path: string;
  onClose: () => void;
}) {
  const kind = previewKind(path);
  const url = api.projectFileUrl(projectId, path);
  const [text, setText] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (kind !== "text") return;
    fetch(url)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((raw) => {
        const clipped = clipPreview(raw);
        setText(clipped.text);
        setTruncated(clipped.truncated);
      })
      .catch(() => setError(true));
  }, [kind, url]);

  return createPortal(
    <div
      role="dialog"
      aria-label={`Preview: ${path}`}
      onClick={onClose}
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-black/80 p-6 backdrop-blur-sm"
    >
      {kind === "image" ? (
        <img
          src={url}
          alt={path}
          onClick={(e) => e.stopPropagation()}
          className="max-h-[82vh] max-w-[90vw] rounded-xl object-contain shadow-2xl"
        />
      ) : kind === "pdf" ? (
        <iframe
          src={url}
          title={path}
          onClick={(e) => e.stopPropagation()}
          className="h-[82vh] w-[min(90vw,64rem)] rounded-xl border-0 bg-white shadow-2xl"
        />
      ) : (
        <div
          onClick={(e) => e.stopPropagation()}
          className="flex max-h-[82vh] w-[min(90vw,52rem)] flex-col overflow-hidden rounded-xl border border-border bg-background shadow-2xl"
        >
          <div className="border-b border-border/60 px-4 py-2.5 font-mono text-xs text-muted-foreground">
            {path}
          </div>
          {error ? (
            <p className="p-4 text-sm text-muted-foreground">Preview unavailable.</p>
          ) : text === null ? (
            <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading…
            </div>
          ) : (
            <>
              {truncated && (
                <p className="px-4 pt-3 text-xs text-primary/80">
                  Preview truncated — download the file for the full content.
                </p>
              )}
              <pre className="overflow-auto whitespace-pre-wrap p-4 font-mono text-[12.5px] leading-relaxed">
                {text || "(empty file)"}
              </pre>
            </>
          )}
        </div>
      )}
      {kind === "image" && (
        <span
          onClick={(e) => e.stopPropagation()}
          className="rounded-md bg-background/80 px-2.5 py-1 font-mono text-[11px] text-foreground backdrop-blur-sm"
        >
          {path}
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
