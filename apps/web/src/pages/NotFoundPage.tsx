import { Compass } from "lucide-react";
import { Link } from "react-router-dom";

/** The catch-all for an unknown path (5E). Before this route existed, App had no fallback at
 *  all, so a stray URL rendered a silent black page (live-confirmed at /projects) — nothing on
 *  screen to say what happened or where to go. */
export function NotFoundPage() {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <Compass className="size-8 text-muted-foreground/50" />
      <h1 className="text-lg font-semibold">This page doesn't exist</h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        There's nothing at this address. Head back to your projects.
      </p>
      <Link
        to="/"
        className="mt-1 inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        Go to Projects
      </Link>
    </div>
  );
}
