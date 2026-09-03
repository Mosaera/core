import { useQuery } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";

import { firstRunApi } from "../../api/firstRun";
import { incompleteBanner } from "../../lib/firstRun";

/** Shown while this instance cannot run anything — for the operator who chose "set this up later".
 *
 *  DERIVED from the live check on every render, never from a stored "setup complete" flag. There is
 *  therefore nothing that can disagree with reality: it appears when the backend stops answering
 *  and disappears by itself the moment it answers again, with no client action and no state to
 *  reconcile. A flag would have to be maintained; a derivation cannot go stale.
 */
export function SetupBanner() {
  const { data, isError } = useQuery({
    queryKey: ["preflight"],
    queryFn: () => firstRunApi.preflight(false),
    refetchInterval: 60_000,
  });
  // A readiness check that FAILED is not a clean bill of health. `ReadyGate` deliberately fails
  // open so a broken endpoint cannot lock everyone out of the app — which left this banner as the
  // only thing that could say so, and it said nothing at all: no wizard, no banner, and the first
  // sign of trouble was a failed run.
  const message = incompleteBanner(data, isError ? "error" : "probed");
  if (!message) return null;
  return (
    <div
      role="status"
      className="flex items-center gap-2 border-b border-primary/30 bg-primary/10 px-4 py-1.5 text-[12px] text-foreground"
    >
      <TriangleAlert aria-hidden className="size-3.5 shrink-0 text-primary" />
      <span className="min-w-0 flex-1">{message}</span>
      <Link to="/settings/models" className="shrink-0 text-primary underline-offset-2 hover:underline">
        Finish setup
      </Link>
    </div>
  );
}
