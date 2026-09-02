/* The run-launch selectors, split out of BacklogItemSheet (2026-08-23). That file is grandfathered
   on the shrink-only god-file ratchet, and giving the operator a way out of Deferred plus a
   labelled evidence link (F66/F68) pushed it over. These are pure presentational controls with no
   sheet state, so they were the honest thing to move rather than a 20-prop footer component. */

import { cn } from "@/lib/utils";

import type { RunMode } from "../../api/client";
import { ConsoleLabel } from "../overview/bits";

const MODE_OPTIONS: { id: RunMode; label: string; hint: string }[] = [
  { id: "guided", label: "Guided", hint: "You approve every gate (writes + delivery)." },
  {
    id: "autonomous",
    label: "Autonomous",
    hint: "Auto-approves when evidence is clear; parks for you only on blocking evidence. Does not chain to the next item.",
  },
  {
    id: "high_assurance",
    label: "High assurance",
    hint: "Works on its own but always asks you before delivering, even when clear.",
  },
];

/** Per-run approval posture picked before launching one item. Guided is the
 *  safe default; a per-run mode never chains to the next item. */
export function ModeSelect({ mode, onChange }: { mode: RunMode; onChange: (m: RunMode) => void }) {
  return (
    <div className="flex flex-col gap-1">
      <ConsoleLabel>Run mode</ConsoleLabel>
      <div role="radiogroup" aria-label="Run mode" className="flex flex-wrap gap-1">
        {MODE_OPTIONS.map((o) => (
          <button
            key={o.id}
            role="radio"
            aria-checked={mode === o.id}
            title={o.hint}
            onClick={() => onChange(o.id)}
            className={cn(
              "rounded-md px-2.5 py-1 font-mono text-[11px] transition-colors",
              mode === o.id
                ? "bg-primary/15 text-primary ring-1 ring-primary/40"
                : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
      <p className="text-[11px] leading-relaxed text-muted-foreground/70">
        {MODE_OPTIONS.find((o) => o.id === mode)?.hint}
      </p>
    </div>
  );
}

/** Cost-mode (routing tier) selector — orthogonal to the approval Run mode above.
 *  Picks which per-role model profile the run uses (configured in Settings). */
export function CostModeSelect({
  modes,
  value,
  onChange,
}: {
  modes: string[];
  value: string;
  onChange: (m: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <ConsoleLabel>Cost mode</ConsoleLabel>
      <div role="radiogroup" aria-label="Cost mode" className="flex flex-wrap gap-1">
        {modes.map((m) => (
          <button
            key={m}
            role="radio"
            aria-checked={value === m}
            onClick={() => onChange(m)}
            className={cn(
              "rounded-md px-2.5 py-1 font-mono text-[11px] capitalize transition-colors",
              value === m
                ? "bg-primary/15 text-primary ring-1 ring-primary/40"
                : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
            )}
          >
            {m}
          </button>
        ))}
      </div>
    </div>
  );
}
