// The /settings/general payload: knob views plus the profile reference block (ADR-0122).
// Split out of `client.ts`, which the size ratchet is working down.

import type { KnobValue, KnobView } from "./client";

/** One knob a profile option sets, with the sentence describing it. */
export interface ProfileEffect {
  field: string;
  value: KnobValue;
  effect: string;
}
/** `{profile field: {choice: effects}}` — served by the API, never duplicated here: the
 *  derivation tables are the server's and a copy would drift invisibly. */
export type ProfileCatalogue = Record<string, Record<string, ProfileEffect[]>>;

export interface GeneralSettings {
  knobs: Record<string, KnobView>;
  profiles?: ProfileCatalogue;
  /** Knobs identical whatever profile is chosen — effort changes how hard the run tries,
   *  never what evidence it must produce. */
  constant?: string[];
  /** Fields a PUT did NOT apply, with why (unknown field, blank/invalid value) — absent on a
   *  plain GET. A genuinely invalid value (negative, out-of-choices) still 400s the whole
   *  request; this is for the fields that used to be silently dropped instead (S4). Empty (or
   *  absent) means everything sent was applied. */
  rejected?: Record<string, string>;
}
