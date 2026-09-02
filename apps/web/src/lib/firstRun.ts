/* The first-run setup copy deck and its derivations (#119) — pure, unit-tested, no React.
 *
 * WHAT THIS IS FOR. A fresh instance used to show one password form and then drop you into an
 * application that could not run anything and did not say so. These strings are how it says so.
 *
 * THE HONESTY RULES, inherited from `lib/plain.ts`:
 *  - A check we could not evaluate is never rendered as a pass. `unknown` is its own word.
 *  - We never name a model as good. The corpus was measured on ONE binding, so a capability
 *    ranking is a claim nobody here can back — the presets route on locality and price, which are
 *    facts, and the operator picks.
 *  - A role that resolved to nothing says so. A silently-substituted model is a run whose producer
 *    was not the one the operator chose.
 */

import type { Preflight, PreflightCheck, PresetPreview, PresetRow } from "../api/firstRun";

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

/* -------------------------------------------------------------------- probe */

/** What the probe found, as the sentence the wizard leads with.
 *
 *  Leading with a finding instead of a blank form is the single biggest difference between a setup
 *  screen a stranger finishes and one they abandon — a machine already running Ollama should be
 *  one click from done, having typed nothing.
 */
export function foundSentence(pf: Preflight | undefined): string {
  if (!pf) return "";
  const { ollama_reachable, ollama_tags } = pf.inventory;
  if (ollama_reachable && ollama_tags.length > 0) {
    const n = ollama_tags.length;
    return `Found Ollama on this machine with ${n} model${n === 1 ? "" : "s"}.`;
  }
  if (ollama_reachable) return "Found Ollama on this machine, but it has no models pulled yet.";
  return "";
}

/** How the probe itself is doing. `error` is NOT a synonym for "found nothing". */
export type ProbeState = "loading" | "error" | "probed";

/** The sentence the wizard leads with, total over all three probe states.
 *
 *  The bug this closes: the lead fell back to "Nothing was found on this machine yet" whenever
 *  `foundSentence` was empty — which includes *the probe is still running* and *the probe failed*.
 *  Both were rendered as a confident negative finding about the machine. `check_images` alone runs
 *  four sequential `docker image inspect` calls at a 5 s timeout, so the window is real, and this
 *  module's own header forbids exactly this: a check we could not evaluate is never rendered as a
 *  result.
 */
export function probeLead(pf: Preflight | undefined, state: ProbeState): string {
  if (state === "loading") return "Checking what this machine has…";
  if (state === "error" || !pf) {
    return "Couldn't check this machine — the readiness check itself failed.";
  }
  return (
    foundSentence(pf) ||
    "Nothing was found on this machine yet. Start Ollama, or connect a provider below."
  );
}

/** Providers whose key is already in this environment — "we found one you already have". */
export function foundKeys(pf: Preflight | undefined): string[] {
  return pf?.inventory.env_keys ?? [];
}

/** True when the probe found something usable, so the wizard can offer a one-click accept. */
export function hasFastPath(pf: Preflight | undefined): boolean {
  if (!pf) return false;
  return Boolean(foundSentence(pf)) || foundKeys(pf).length > 0;
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

/** Rows the operator needs to act on. A screen that lists everything equally makes the reader do
 *  the triage; `note` is informational and does not belong here. */
export function actionable(pf: Preflight | undefined): PreflightCheck[] {
  return (pf?.checks ?? []).filter((c) => c.status === "fail" || c.status === "unknown");
}

/* ------------------------------------------------------------------ presets */

/** Human labels for the shipped preset ids.
 *
 *  KNOWN DIVERGENCE: `presetLabel` in `lib/models.ts` (the Settings page) still spells these
 *  "Local · Free / Balanced / Quality · Cloud". They were remapped here and not there, so the two
 *  screens name the same three presets differently. This comment states the divergence rather than
 *  claiming a consistency that does not hold. */
export const PRESET_LABEL: Record<string, string> = {
  economy: "On this machine only",
  balanced: "Cheapest available",
  premium: "I'll choose",
};

/** Whether this preset resolved every role. `false` means at least one role has no model, which
 *  the review must show rather than paper over. */
export function fullyResolved(preset: PresetPreview | undefined): boolean {
  return Boolean(preset && preset.resolution.length > 0 && preset.resolution.every((r) => r.model));
}

/** The roles a preset could NOT serve. */
export function unresolvedRoles(preset: PresetPreview | undefined): string[] {
  return (preset?.resolution ?? []).filter((r) => !r.model).map((r) => r.role);
}

/** One line when every role landed on the same model, else "". Lets the review collapse — a table
 *  of five identical rows is a chore, and a chore before first value is where people leave. */
export function uniformSummary(preset: PresetPreview | undefined): string {
  const rows = preset?.resolution ?? [];
  if (rows.length === 0 || !rows.every((r) => r.model)) return "";
  const first = `${rows[0].provider}/${rows[0].model}`;
  const same = rows.every((r) => `${r.provider}/${r.model}` === first);
  return same ? `all ${rows.length} roles → ${rows[0].model}` : "";
}

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

export function incompleteBanner(pf: Preflight | undefined, state: ProbeState = "probed"): string {
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

/* ------------------------------------------------------- per-role overrides */

/** A role's chosen binding, keyed by role. Absent = take the preset's own resolution. */
export type RoleOverrides = Record<string, { provider: string; model: string }>;

/** The preset's resolution with the operator's per-role choices applied.
 *
 *  Why this exists: the review step was a read-only list, so on a machine where a preset resolved
 *  nothing — the DEFAULT state of a clean VM — every role read "not resolved", "Confirm and
 *  continue" was disabled with no explanation, and step 1's promise that "you'll pick on the next
 *  screen" pointed at a screen with no picker. "I'll choose" was impossible to complete. Overriding
 *  here keeps the write path unchanged: the same rows, the same `saveCostModes` call, no new
 *  authority. */
export function effectiveResolution(
  preset: PresetPreview | undefined,
  overrides: RoleOverrides,
): PresetRow[] {
  return (preset?.resolution ?? []).map((row) => {
    const pick = overrides[row.role];
    if (!pick || !pick.model) return row;
    return { ...row, provider: pick.provider, model: pick.model, reason: "you chose this one" };
  });
}

/** Whether every role has a binding once the operator's choices are applied. */
export function resolvedWithOverrides(
  preset: PresetPreview | undefined,
  overrides: RoleOverrides,
): boolean {
  const rows = effectiveResolution(preset, overrides);
  return rows.length > 0 && rows.every((r) => r.model);
}

/** `provider/model` as one token — the value a per-role <Select> carries. */
export function bindingKey(provider: string, model: string): string {
  return `${provider}/${model}`;
}

/** Split a `bindingKey` apart. A model id may itself contain "/" (e.g. `org/model:tag`), so only
 *  the FIRST separator is structural. */
export function parseBindingKey(key: string): { provider: string; model: string } {
  const cut = key.indexOf("/");
  return cut < 0
    ? { provider: "", model: key }
    : { provider: key.slice(0, cut), model: key.slice(cut + 1) };
}
