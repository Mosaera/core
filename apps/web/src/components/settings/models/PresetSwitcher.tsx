import { Lock, ShieldAlert } from "lucide-react";

import { cn } from "@/lib/utils";

import { type CostModesState } from "../../../api/client";
import { egressConsequence, presetLabel, type EffectiveBinding } from "../../../lib/models";

/** The anchor of the Models screen: a segmented control over the cost-mode presets
 *  (relabeled for humans). One click makes a preset the default for new runs and
 *  reassigns every role; below it, a truthful plain-language consequence line —
 *  all-local is calm, any cloud role names what leaves the box. Most operators
 *  never scroll past this. */
export function PresetSwitcher({
  costModes,
  activePreset,
  localProviderIds,
  onSelect,
}: {
  costModes: CostModesState;
  activePreset: string;
  localProviderIds: Set<string>;
  onSelect: (mode: string) => void;
}) {
  const effective: EffectiveBinding[] = costModes.role_meta.map((m) => {
    const cell = costModes.modes[activePreset]?.[m.role];
    return {
      role: m.role,
      label: m.label,
      provider: cell?.effective_provider ?? "",
      model: cell?.effective_model ?? "",
    };
  });
  const egress = egressConsequence(effective, localProviderIds);

  return (
    <section aria-label="Preset" className="flex flex-col items-stretch gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-xl font-semibold tracking-tight">Which models run your team</h2>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Pick a preset to assign every role at once, then fine-tune below. Your choice is the
          default for new runs.
        </p>
      </div>

      <div
        role="tablist"
        aria-label="Preset"
        className="inline-flex w-fit max-w-full flex-wrap gap-1 rounded-lg bg-muted/40 p-1"
      >
        {costModes.available.map((mode) => {
          const active = mode === activePreset;
          return (
            <button
              key={mode}
              role="tab"
              aria-selected={active}
              onClick={() => onSelect(mode)}
              className={cn(
                "rounded-md border-0 px-3 py-1.5 text-sm font-medium transition-colors",
                active
                  ? "bg-background text-foreground shadow-sm ring-1 ring-white/12"
                  : "bg-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {presetLabel(mode)}
            </button>
          );
        })}
      </div>

      <div
        className={cn(
          "flex items-start gap-2 rounded-lg px-3 py-2.5 text-sm leading-relaxed",
          egress.usesCloud
            ? "bg-amber-500/10 text-amber-700 dark:text-amber-300"
            : "bg-success/10 text-success",
        )}
      >
        {egress.usesCloud ? (
          <ShieldAlert className="mt-0.5 size-4 shrink-0" />
        ) : (
          <Lock className="mt-0.5 size-4 shrink-0" />
        )}
        <span>{egress.text}</span>
      </div>
    </section>
  );
}
