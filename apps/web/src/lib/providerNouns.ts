/** Provider-neutral vocabulary for the delivery surfaces (S4 audit, ADR-0112/0114).
 *
 *  Every delivery/changes/backlog surface used to hardcode "MR" / "merge request" / "GitLab"
 *  regardless of which forge a project actually delivers to — accurate for a GitLab project,
 *  wrong for a connected GitHub one (which opens a *pull request*), and misleading for a
 *  project with no remote configured at all. `capability.provider` (from
 *  `GET /projects/{id}/delivery/capability`, ADR-0112) is the one place that already knows
 *  which forge a project targets; every surface below routes its copy through this helper
 *  instead of re-deriving or hardcoding the noun.
 *
 *  Deliberately narrow: a lookup table, not a copy-generation system. Adding a third forge
 *  means adding one more case here, not touching every surface that calls it. */

export type DeliveryProvider = "gitlab" | "github" | "unknown" | null | undefined;

export interface ProviderNouns {
  /** lowercase noun for the request kind this provider opens, e.g. "merge request" */
  request: string;
  /** same, capitalized for sentence starts, e.g. "Merge request" */
  Request: string;
  /** short form for compact UI, e.g. "MR" */
  short: string;
  /** the forge's product name, e.g. "GitLab" — "the remote" when unknown/local */
  hostName: string;
}

const GITLAB: ProviderNouns = {
  request: "merge request",
  Request: "Merge request",
  short: "MR",
  hostName: "GitLab",
};

const GITHUB: ProviderNouns = {
  request: "pull request",
  Request: "Pull request",
  short: "PR",
  hostName: "GitHub",
};

/** Neutral fallback for a local project, an unconnected remote, or a provider this build
 *  doesn't recognise yet — never guesses GitLab just because that's the first forge Mosaera
 *  supported (ProjectSettingsWorkspace's provider flash, F8/F9/F10, is the bug this avoids). */
const NEUTRAL: ProviderNouns = {
  request: "change request",
  Request: "Change request",
  short: "request",
  hostName: "the remote",
};

/** Look up the copy for a project's delivery provider. `undefined`/`null`/`"unknown"` (capability
 *  still loading, an older server, or a genuinely undetermined source) resolve to the neutral
 *  fallback rather than defaulting to either real forge's vocabulary. */
export function providerNouns(provider: DeliveryProvider): ProviderNouns {
  if (provider === "gitlab") return GITLAB;
  if (provider === "github") return GITHUB;
  return NEUTRAL;
}
