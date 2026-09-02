/* Project-setup API calls + their types, split out of client.ts (ADR-0113 — client.ts is at its
   grandfathered line ratchet, and `api/delivery.ts` set the precedent for this split). Spread into
   the `api` object in client.ts, so call sites keep using `api.projectSetup(...)` unchanged. */

import { adminFetch } from "./adminAuth";
import { apiFetch } from "./auth";
import { type CharterPosture, type Project, json } from "./client";

/** The onboarding read (#121): the repo as MEASURED, plus every choice with its server-declared
 *  option set. `available: false` means the clone is not readable yet — intake clones in the
 *  background, so that is the ordinary first read and must never render as a shape. */
export interface ProjectSetup {
  completed_at?: string | null;
  current: {
    run_mode: string;
    posture: CharterPosture;
    test_cmd: string;
    tester_enabled: boolean;
    budget_usd: number | null;
    budget_tokens: number | null;
  };
  /** Rendered as dropdowns; the write path validates against these same sets (ADR-0005). */
  choices: { run_mode: string[]; posture: string[]; cost_mode: string[] };
  /** `source` = env | stored | default (env-pinned is read-only); `clamped_by` names a knob that
   *  overrides this one on some runs. */
  tester_knob?: { value?: boolean; source?: string; clamped_by?: string | null };
  available: boolean;
  reason?: string;
  shapes?: string[];
  repo_shape?: {
    shape: string;
    source_files: number;
    test_files: number;
    plan_strength: string;
    plan_reason: string;
    project_type: string;
    truncated: boolean;
    needs_an_oracle: boolean;
    evidence: string[];
  };
  oracle_plan?: {
    legs: Record<string, boolean>;
    verified_possible: boolean;
    recommended_knobs: string[];
    recommend_test_cmd: boolean;
  };
}

export interface SetupPatch {
  run_mode?: string;
  posture?: string;
  test_cmd?: string;
  tester_enabled?: boolean;
  budget_usd?: number | null;
  budget_tokens?: number | null;
  completed?: boolean;
}

export const projectSetupApi = {
  projectSetup: (id: string) =>
    apiFetch(`/api/projects/${id}/setup`).then(json<ProjectSetup>),

  /** Re-run a clone that failed. Onboarding's true first step is the clone, and until this existed
   *  a failed one was terminal: `run_intake` parks the project at status "draft" with an error and
   *  nothing restarted it — not even connecting GitLab, which is the fix the New-project page
   *  tells you to apply. 202 + the refreshed project; 409 when there is no failed intake. */
  retryIntake: (id: string) =>
    apiFetch(`/api/projects/${id}/intake/retry`, { method: "POST" }).then(json<Project>),

  // adminFetch: the body may carry the ADR-0046 posture or the deployment-global Proctor knob, and
  // the server gates those. A member's save simply omits them, which the server reads as
  // "leave alone" — so the admin header is attached when available and never required.
  saveProjectSetup: (id: string, body: SetupPatch) =>
    adminFetch(`/api/projects/${id}/setup`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<ProjectSetup>),
};
