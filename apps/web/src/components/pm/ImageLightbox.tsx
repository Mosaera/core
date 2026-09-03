import { X } from "lucide-react";
import { useEffect } from "react";
import { createPortal } from "react-dom";

/** Expanded image overlay: click the backdrop (anywhere off the picture) or
 *  press Escape to close. Shows the ORIGINAL image, not the thumbnail. */
export function ImageLightbox({
  src,
  alt,
  onClose,
}: {
  src: string;
  alt: string;
  onClose: () => void;
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div
      role="dialog"
      aria-label={`Image preview: ${alt}`}
      onClick={onClose}
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-black/80 p-6 backdrop-blur-sm"
    >
      <img
        src={src}
        alt={alt}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[82vh] max-w-[90vw] rounded-xl object-contain shadow-2xl"
      />
      <span
        onClick={(e) => e.stopPropagation()}
        className="rounded-md bg-background/80 px-2.5 py-1 font-mono text-[11px] text-foreground backdrop-blur-sm"
      >
        {alt}
      </span>
      <button
        type="button"
        aria-label="Close image preview"
        onClick={onClose}
        className="absolute right-4 top-4 cursor-pointer rounded-full border-0 bg-background/80 p-2 text-foreground shadow-none backdrop-blur-sm hover:bg-background"
      >
        <X className="size-4" />
      </button>
    </div>,
    document.body,
  );
}
