import { cn } from "@/lib/utils";

/** The shared settings surface — the `bg-card` panel every settings section uses.
 *  `items-stretch` defeats the legacy `.flex { align-items:center }` cascade so
 *  content stays left-aligned. `danger` swaps the ring for the destructive tone. */
export function SettingsCard({
  children,
  danger,
  className,
  label,
}: {
  children: React.ReactNode;
  danger?: boolean;
  className?: string;
  label?: string;
}) {
  return (
    <section
      aria-label={label}
      className={cn(
        "flex flex-col items-stretch gap-3 rounded-lg bg-card p-4 ring-1",
        danger ? "ring-destructive/40" : "ring-white/12",
        className,
      )}
    >
      {children}
    </section>
  );
}
