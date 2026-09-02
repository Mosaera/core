import { ChevronLeft } from "lucide-react";
import { Link } from "react-router-dom";

/** The frame both provider panels share: a back link to the Git index and a header card
 *  naming the provider.
 *
 *  It exists so GitHub and GitLab read as the same product even though their handshakes are
 *  genuinely different — GitLab authorizes through a redirect, GitHub resolves an App
 *  installation server-side, and that difference is a security argument (ADR-0114), not an
 *  inconsistency to paper over. Shared shell, shared vocabulary; the one step that differs is
 *  the only thing that looks different. */
export function ConnectionShell({
  mark,
  title,
  description,
  children,
}: {
  mark: React.ReactNode;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-stretch gap-6">
      <Link
        to="/settings/git"
        className="flex w-fit items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronLeft className="size-4" aria-hidden />
        Git
      </Link>

      <div className="flex items-center gap-3 rounded-lg bg-card p-4 ring-1 ring-white/12">
        <span className="shrink-0 text-foreground">{mark}</span>
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 className="text-base font-semibold tracking-tight text-foreground">{title}</h2>
          <p className="text-[12.5px] text-muted-foreground">{description}</p>
        </div>
      </div>

      {children}
    </div>
  );
}

/** A titled block inside a provider panel. Flat, like `SettingsSection`, so a panel reads as
 *  one page rather than a stack of cards — the console idiom the rest of Settings uses. */
export function PanelSection({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title} className="flex flex-col items-stretch gap-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}
