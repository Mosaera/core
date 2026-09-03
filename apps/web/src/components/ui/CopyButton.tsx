import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

/** The house copy-to-clipboard affordance: Copy → ✓ for ~1.5s, insecure-origin
 *  safe (a blocked clipboard is a silent no-op). `text` may be a string or a
 *  producer (for lazily-built exports). Callers style via className; the aria
 *  label stays theirs so existing accessibility queries keep working. */
export function CopyButton({
  text,
  label,
  copiedLabel,
  title,
  className,
  iconClassName = "size-3.5",
}: {
  text: string | (() => string);
  label: string;
  /** aria-label while in the copied state (defaults to `label`). */
  copiedLabel?: string;
  title?: string;
  className?: string;
  iconClassName?: string;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard?.writeText(typeof text === "function" ? text() : text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked (insecure origin / denied) — a silent no-op */
    }
  }
  return (
    <button
      type="button"
      onClick={() => void copy()}
      aria-label={copied ? (copiedLabel ?? label) : label}
      title={title ?? label}
      className={cn(
        "flex size-6 shrink-0 cursor-pointer items-center justify-center rounded border-0 bg-transparent p-0 text-muted-foreground/70 hover:bg-muted/50 hover:text-foreground",
        copied && "text-success",
        className,
      )}
    >
      {copied ? (
        <Check className={cn(iconClassName, "text-success")} />
      ) : (
        <Copy className={iconClassName} />
      )}
    </button>
  );
}
