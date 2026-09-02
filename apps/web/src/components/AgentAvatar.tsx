/* One circular avatar for a run persona. Personas we have art for (Quincy,
   Forge, Rook) render their headshot; the rest fall back to a monogram in the
   same box, so a mixed timeline stays aligned instead of looking broken.

   The headshots are pre-cropped to a circle with a real alpha channel, so no
   background shows through at the corners. Sizing is set explicitly because
   index.css deliberately skips Tailwind Preflight (the legacy stylesheet still
   lives in a cascade layer), so <img> gets no display/reset from the framework. */

import { avatarFor } from "@/components/runs/runActors";
import { cn } from "@/lib/utils";

interface AgentAvatarProps {
  actor: string;
  /** Rendered box, in px. Also the fallback monogram's box. */
  size?: number;
  className?: string;
  /** Override the fallback letter. Every actor here is named "The …", so the default first
   *  character is a "T" that identifies nobody — a caller that knows a better letter passes it. */
  monogram?: string;
}

export function AgentAvatar({ actor, size = 24, className, monogram }: AgentAvatarProps) {
  const src = avatarFor(actor);
  const box = { width: size, height: size } as const;

  if (!src) {
    return (
      <span
        aria-hidden="true"
        style={box}
        className={cn(
          "inline-flex shrink-0 select-none items-center justify-center rounded-full",
          "border border-border bg-muted font-medium text-muted-foreground",
          className,
        )}
        // Keep the letter legible at any box size.
        {...{ "data-actor": actor }}
      >
        <span style={{ fontSize: Math.max(9, Math.round(size * 0.42)), lineHeight: 1 }}>
          {(monogram || actor).charAt(0).toUpperCase()}
        </span>
      </span>
    );
  }

  return (
    <img
      src={src}
      alt="" // decorative: the actor's name is always rendered next to it
      style={box}
      className={cn("inline-block shrink-0 select-none rounded-full object-cover object-top", className)}
    />
  );
}
