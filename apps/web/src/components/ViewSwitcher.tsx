import { cn } from "@/lib/utils";

/** Segmented control over a section's internal views (Phase 9 consolidation: Changes +
 *  Artifacts folded into Delivery, Activity folded into Runs — same components, fewer entry
 *  points). Same tablist idiom as `settings/models/PresetSwitcher` so a switcher reads the
 *  same wherever one appears. */
export function ViewSwitcher<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly { id: T; label: string }[];
  onChange: (next: T) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className="inline-flex w-fit max-w-full flex-wrap gap-1 rounded-lg bg-muted/40 p-1"
    >
      {options.map((o) => {
        const active = o.id === value;
        return (
          <button
            key={o.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.id)}
            className={cn(
              "rounded-md border-0 px-3 py-1.5 text-sm font-medium transition-colors",
              active
                ? "bg-background text-foreground shadow-sm ring-1 ring-white/12"
                : "bg-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
