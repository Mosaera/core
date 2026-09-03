import { cn } from "@/lib/utils";

/** The shared settings surface — a cardless page section: an `h2` title, an
 *  optional description, and an optional right-aligned `action` (e.g. a Save
 *  button or a status chip), above the section's content. Every Settings section
 *  uses this so they read as one flat, enterprise console rather than a stack of
 *  floating cards. `items-stretch` defeats the legacy `.flex { align-items:center }`
 *  cascade so content stays left-aligned. */
export function SettingsSection({
  title,
  description,
  action,
  tone = "default",
  className,
  children,
}: {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  /** `danger` colors the title destructive — the flat replacement for a red-ringed card. */
  tone?: "default" | "danger";
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title} className={cn("flex flex-col items-stretch gap-8", className)}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <h2
            className={cn(
              "text-xl font-semibold tracking-tight",
              tone === "danger" && "text-destructive",
            )}
          >
            {title}
          </h2>
          {description && <div className="max-w-2xl">{description}</div>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
