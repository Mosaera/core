/* Readiness copy + derivations shared by the SetupBanner and the Settings->Models health panel
 * (#119) — pure, unit-tested, no React.
 *
 * WHAT THIS IS FOR. A fresh instance used to show one password form and then drop you into an
 * application that could not run anything and did not say so. These strings are how it says so.
 * The first-run WIZARD itself moved to the terminal (ADR-0116, `apps/api/mosaera_api/setup/`);
 * what is left here is the part still reachable from inside the running app — the banner, and the
 * health panel that answers "why" once you click through it.
 *
 * THE HONESTY RULES, inherited from `lib/plain.ts`:
 *  - A check we could not evaluate is never rendered as a pass. `unknown` is its own word.
 */

import type { Preflight, PreflightCheck } from "../api/firstRun";

/* ------------------------------------------------------------------ statuses */

/** How a check reads. `note` is deliberately not a failure — running without a database is a
 *  supported state, and calling it broken would be as dishonest as calling it fine. */
export const STATUS_LABEL: Record<string, string> = {
  ok: "ready",
  fail: "needs fixing",
  unknown: "couldn't check",
  note: "heads up",
};

export type StatusTone = "success" | "amber" | "muted";

export function statusTone(status: string): StatusTone {
  if (status === "ok") return "success";
  if (status === "fail") return "amber";
  return "muted";
}

/* ------------------------------------------------------------------- checks */

/** Environment rows, in a fixed order so the screen does not reshuffle between polls. */
export function environmentChecks(pf: Preflight | undefined): PreflightCheck[] {
  const order = ["docker", "images", "database"];
  return (pf?.checks ?? [])
    .filter((c) => order.includes(c.key))
    .sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
}

/** The model-backend rows — the ones `can_run` actually turns on. */
export function backendChecks(pf: Preflight | undefined): PreflightCheck[] {
  return (pf?.checks ?? []).filter((c) => c.key.startsWith("backend"));
}

/* --------------------------------------------------------------------- banner */

/** The banner shown to someone who deferred setup. Derived from the live check, so it clears
 *  itself the moment the backend answers — there is no "setup complete" flag to go stale. */
export function setupConsequence(pf: Preflight | undefined): string {
  // The consequence is the server's, not ours to guess. A config gap is REFUSED at submit by
  // `guard_can_run`; an unreachable backend is accepted and then fails at the first model call.
  // Saying "refused" for both is a promise the server does not keep — seen live, 2026-08-24. ONE
  // origin, read by the banner AND the wizard's lede: the lede went on claiming "nothing will run"
  // after the banner was fixed, which is how one sentence in two places drifts.
  return pf?.blocks_launch
    ? "Runs will be refused until it is."
    : "Runs will start but fail at the first model call.";
}

export function incompleteBanner(pf: Preflight | undefined, state: "loading" | "error" | "probed" = "probed"): string {
  // A probe that FAILED is not a healthy instance. Returning "" for any absent payload meant a 500
  // from /api/preflight showed no wizard AND no banner: the operator was told nothing at all and
  // found out at the first run.
  if (state === "error") {
    return "Couldn't check whether this instance is ready to run — the readiness check failed.";
  }
  if (!pf || pf.can_run) return "";
  return pf.reason
    ? `Setup isn't finished — ${pf.reason}. ${setupConsequence(pf)}`
    : `Setup isn't finished. ${setupConsequence(pf)}`;
}
