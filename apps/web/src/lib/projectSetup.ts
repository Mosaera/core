/* The onboarding copy deck and its derivations (#121) — pure, unit-tested, no React.
 *
 * WHAT THIS FILE IS FOR. A newcomer's project is almost always greenfield, and a greenfield run's
 * default terminal state is a PARK: the delivery gate needs one of four independence legs to vouch
 * and a fresh repo supplies none of them, so a green self-authored suite still stops at
 * `oracle_unverified`. That was operator folklore. These sentences are how the product says it.
 *
 * THE HONESTY RULES THE WORDS MAY NOT SOFTEN, inherited from `plain.ts`:
 *  - Every number here is MEASURED and carries its source. No projections, no "typically".
 *  - A shape the server could not determine is never given a sentence — the caller renders the
 *    server's own `reason` instead.
 *  - The greenfield delivery rate is stated because it is true, not because it is encouraging.
 *    Miscalibrated expectations are the thing that makes an operator stop trusting the next
 *    sentence, and this product's whole claim is that its statements can be checked.
 *
 * The option LABELS are ours; the option SETS are the server's (`choices`), so a value the UI can
 * offer is always a value the write path accepts (ADR-0005).
 */

import type { ProjectSetup } from "../api/client";

/* ----------------------------------------------------------------- repo shape */

/** One sentence per shape, addressed to the operator. Keys are `reposhape.SHAPES`. */
export const SHAPE_HEADLINE: Record<string, string> = {
  empty: "This repository is empty — everything here gets built from scratch.",
  greenfield: "This repository has code but no tests.",
  sources_no_suite: "This repository has test files, but none of them asserts anything real.",
  standing_suite: "This repository already has a test suite that asserts real behaviour.",
};

/** The honest expectation, per shape. Measured on the corpus; the source is named because a number
 *  without one is the thing the instrument-trust rule exists to stop. */
export const SHAPE_EXPECTATION: Record<string, string> = {
  empty:
    "Building from nothing is the regime we have measured worst — roughly a third to two fifths " +
    "of items deliver on the first run.",
  greenfield:
    "Building from nothing is the regime we have measured worst — roughly a third to two fifths " +
    "of items deliver on the first run.",
  sources_no_suite:
    "Test files that assert nothing cannot vouch for new work, so this behaves like a repository " +
    "with no tests at all.",
  standing_suite:
    "An existing suite that covers the code being changed is the strongest starting position " +
    "this product has.",
};

/** The "what this means" disclosure: why a run parks, in the operator's terms. One paragraph,
 *  behind a toggle — the research is unambiguous that a wall of caveats before first value is
 *  what makes people leave, and that acknowledging limits is what makes them stay. */
export const PARK_EXPLAINER =
  "When work finishes, something independent has to vouch for it before it can ship. The code's " +
  "own tests do not count — they were written by the same agent that wrote the code, so they " +
  "prove only that it agrees with itself. If nothing independent can vouch, the run stops and " +
  "asks you instead of shipping. That stop is the product working, but on a fresh repository it " +
  "is also the default outcome unless you give it one of the options below.";

/* ------------------------------------------------------------------ run modes */

/** Labels for the approval modes. The ids are `RUN_MODES`, served by the API; the plain names
 *  follow ADR-0101 (ask / accept / auto) while the ids keep the ADR-0012 vocabulary the engine
 *  still speaks. */
export const RUN_MODE_LABEL: Record<string, string> = {
  guided: "Guided",
  autonomous: "Autonomous",
  high_assurance: "High assurance",
};

export const RUN_MODE_HINT: Record<string, string> = {
  guided: "You approve every write and the delivery. Slowest, and nothing happens unwatched.",
  autonomous:
    "Approves itself when the evidence is clear and stops for you when it is not. It never ships " +
    "past the delivery gate — that check is not yours to waive, or its.",
  high_assurance: "Works on its own, then always asks you before delivering, even when clear.",
};

/** Why the card opens on `guided`: autonomy is something you widen once you have watched it work,
 *  and it is also the only direction ADR-0046's lattice lets a posture move. */
export const RUN_MODE_DEFAULT_NOTE =
  "Starts at the most supervised setting. Widen it once you have watched a run or two — you can " +
  "also change it per run at launch.";

/* ------------------------------------------------------------------- postures */

/** The ADR-0046 governance tiers. Deliberately described as a DIFFERENT axis from run mode: the
 *  two were conflated in the issue that asked for this flow, and an operator who thinks they are
 *  the same thing will set one expecting the other. */
export const POSTURE_HINT: Record<string, string> = {
  free: "Solo operator. Unattended delivery is allowed, subject to the evidence gate.",
  business: "Commercial default. Autonomy is granted by configuration and revocable at any time.",
  regulated: "Nothing ships without a human decision.",
};

export const POSTURE_AXIS_NOTE =
  "A different axis from run mode: run mode is how much this project asks you during a run; " +
  "posture is what this deployment permits at all. An administrator sets it.";

/* --------------------------------------------------------------- oracle plan */

/** Human names for the four independence routes (`_oracle_legs.LEG_NAMES`). */
export const LEG_LABEL: Record<string, string> = {
  tester_vouched: "The Proctor writes the acceptance test",
  standing_suite: "The repository's existing suite covers the change",
  test_cmd: "Your own test command decides",
  structural_vouch: "The change's shape is checked directly",
};

/** What a pass of the detected validation plan is WORTH (`ValidationPlan.strength`). */
export const STRENGTH_PLAIN: Record<string, string> = {
  suite: "a real test suite runs",
  shallow: "only checks that the code parses",
  none: "nothing is executed",
  unknown: "no check plan could be built",
};

export const PROCTOR_DEPLOYMENT_WIDE =
  "This is a deployment-wide setting: turning the Proctor on turns it on for every project here, " +
  "not just this one.";

/* --------------------------------------------------------------------- budget */

/** What we can honestly say about cost at setup time.
 *
 *  A per-item cost is a MEASURED quantity — `project_estimate` prices this project's own historical
 *  per-role token load — and a brand-new project has no history to price. So the card states the
 *  absence rather than a "typical" figure. An invented number here would be the exact
 *  instrument-trust violation this product exists to argue against, and it would be the first
 *  number a newcomer ever reads from us. */
export const BUDGET_NO_DATA =
  "No cost has been measured for this project yet — a per-item figure appears here once runs have " +
  "been metered. Until then a cap is a ceiling, not a prediction.";

export const BUDGET_HINT =
  "A monthly ceiling on this project's spend. Reaching it pauses an autonomous sweep between " +
  "items; it does not interrupt a run in flight. Leave blank for no cap.";

/* ------------------------------------------------------------- derived state */

export interface SetupDraft {
  run_mode: string;
  posture: string;
  test_cmd: string;
  tester_enabled: boolean;
  /** Monthly USD ceiling; null = no cap. A ceiling, never a prediction (see BUDGET_NO_DATA). */
  budget_usd: number | null;
}

/** The card's PRE-FILLED starting values: what is stored, plus the recommendation applied.
 *
 *  This is what makes "Looks right" a one-click path — the research on activation is blunt that a
 *  form of blank fields is where people leave. The recommendation only ever turns something ON to
 *  make verification possible; it never relaxes anything, and it is visible before it is saved.
 */
export function initialDraft(setup: ProjectSetup): SetupDraft {
  const recommended = setup.oracle_plan?.recommended_knobs ?? [];
  // A recommendation is only pre-applied when the knob can ACTUALLY be set from here. An
  // env-pinned knob is read-only (env > stored, ADR-0005), so pre-filling it would show a card
  // claiming the project can be verified while the toggle that would deliver that is disabled and
  // the save is a no-op — a promise the product cannot keep, which is worse than the warning.
  const settable = setup.tester_knob?.source !== "env";
  return {
    run_mode: setup.current.run_mode,
    posture: setup.current.posture,
    test_cmd: setup.current.test_cmd,
    tester_enabled:
      setup.current.tester_enabled || (settable && recommended.includes("tester_enabled")),
    // Never pre-filled with a suggested cap: we have no measured per-item cost for a new project,
    // so any number we put here would be invented.
    budget_usd: setup.current.budget_usd,
  };
}

/** True when the pre-filled draft would CHANGE something — i.e. the card is proposing, not just
 *  reflecting. Used to label the primary button honestly. */
export function draftChangesSomething(setup: ProjectSetup, draft: SetupDraft): boolean {
  const c = setup.current;
  return (
    draft.run_mode !== c.run_mode ||
    draft.posture !== c.posture ||
    draft.test_cmd !== c.test_cmd ||
    draft.tester_enabled !== c.tester_enabled ||
    draft.budget_usd !== c.budget_usd
  );
}

/** Whether the draft, if saved, would let something vouch for this project's work.
 *
 *  Recomputed on the CLIENT from the same disjunction the gate evaluates, so the card can answer
 *  "will this actually help?" as the operator toggles — without claiming a run will pass. A
 *  standing suite is the server's measurement; the other two legs are the operator's own choices.
 */
export function draftCanBeVerified(setup: ProjectSetup, draft: SetupDraft): boolean {
  const standingSuite = setup.oracle_plan?.legs.standing_suite === true;
  return standingSuite || draft.tester_enabled || draft.test_cmd.trim().length > 0;
}

/** The one-line warning when nothing would vouch. Empty when something would — a warning that is
 *  always on is a warning nobody reads. */
export function unverifiableWarning(setup: ProjectSetup, draft: SetupDraft): string {
  if (draftCanBeVerified(setup, draft)) return "";
  return (
    "As set, nothing independent can vouch for this project's work — every run will stop and ask " +
    "you, however good the code is. Turn on the Proctor, or give a test command."
  );
}

/** The knob's provenance, when it is not simply editable here. Empty string = it is editable. */
export function testerKnobNote(setup: ProjectSetup): string {
  const knob = setup.tester_knob ?? {};
  if (knob.source === "env")
    return "Pinned by an environment variable on the server — it cannot be changed from here.";
  if (knob.clamped_by)
    return `Autonomous runs turn this on regardless, because ${knob.clamped_by} is on.`;
  return "";
}
