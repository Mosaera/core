/* First-run setup API + types (#119).
 *
 * Imported DIRECTLY by its callers (`firstRunApi.preflight(...)`) rather than spread into the `api`
 * object the way `api/delivery.ts` is. That is a deliberate, small deviation from the house idiom:
 * `client.ts` sits at a shrink-only line ratchet, and spreading costs it two lines it may not
 * grow. Refactoring shared code to buy them — in a file another session is also editing — would be
 * a worse trade than one explicit import. */

import { apiFetch } from "./auth";
import { json } from "./client";

/** One readiness question, its answer, and the command that fixes it.
 *  `status` is the honest tri-state; `ok` is the two-state view — `unknown` reads as NOT ok. */
export interface PreflightCheck {
  key: string;
  label: string;
  status: "ok" | "fail" | "unknown" | "note";
  ok: boolean;
  detail: string;
  /** A copy-pasteable command, never prose. Empty when nothing needs doing. */
  fix: string;
}

/** What this box HAS — the wizard leads with this instead of a blank form. */
export interface PreflightInventory {
  ollama_reachable: boolean | null;
  ollama_tags: string[];
  ollama_error: string;
  /** Hosted providers whose native API-key env var is already set. */
  env_keys: string[];
}

export interface Preflight {
  checks: PreflightCheck[];
  inventory: PreflightInventory;
  /** THE predicate: is there a reachable, credentialed model backend? */
  can_run: boolean;
  reason: string;
  /** Whether a launch is actually REFUSED (a config gap), as opposed to merely doomed (an
   *  unreachable backend, which the run itself fails loudly on). The two are different questions
   *  and the banner must not promise the one the server does not perform. */
  blocks_launch: boolean;
}

export const firstRunApi = {
  /** `verify=false` skips the provider round-trip — used while the operator is still typing, so a
   *  half-entered key is never sent anywhere. */
  preflight: (verify = true) =>
    apiFetch(`/api/preflight?verify=${verify ? "true" : "false"}`).then(json<Preflight>),
};

/* `testProvider` is NOT re-declared here: `client.ts` already owns it, admin-gated and returning
   the models the key grants. The wizard calls that one. A second wrapper over the same endpoint is
   how two callers end up sending different bodies to it. */
