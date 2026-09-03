import { cn } from "@/lib/utils";

/** A dot with a halo that pulses outward — "something is happening right now".
 *
 *  Lifted out of the run hero so there is one of these rather than two that drift. The colour is
 *  a prop because the hero means "this run is live" (success green) and the chat means "he is
 *  working on it" (primary).
 *
 *  `motion-reduce:animate-none` on the halo: a pulsing dot is precisely what someone who has
 *  asked for reduced motion has asked not to see, and the solid dot alone still says "live".
 *  `aria-hidden` because the words beside it carry the meaning. */
export function PulseDot({ className }: { className?: string }) {
  return (
    <span className="relative flex size-2" aria-hidden>
      <span
        className={cn(
          "absolute inline-flex size-full animate-ping rounded-full opacity-60 motion-reduce:animate-none",
          className ?? "bg-primary",
        )}
      />
      <span className={cn("relative inline-flex size-2 rounded-full", className ?? "bg-primary")} />
    </span>
  );
}
