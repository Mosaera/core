/* Delivery-surface API calls, split out of client.ts (ADR-0103 — client.ts was at its
   1070-line ratchet ceiling). Spread into the `api` object in client.ts, so call sites keep
   using `api.projectDiff(...)` etc. unchanged. */

import { adminFetch } from "./adminAuth";
import { apiFetch } from "./auth";
import { json } from "./client";

/** Operator edits for a merge request before it is sent (ADR-0103). All optional. Takes effect
 *  only when the project has an api-scoped token; otherwise the server degrades to push-options. */
export interface MrCompose {
  title?: string;
  body?: string;
  target_branch?: string;
  squash?: boolean;
  remove_source_branch?: boolean;
  labels?: string[];
  /** A2: cherry-pick only these commits into the MR branch; omit for the whole branch. */
  commit_shas?: string[];
}

/** One project branch (from the local clone — feeds the target-branch picker). */
/** Where the working branch stands against the base. Computed WITHOUT a fetch, so `behind` is
 *  null in the `behind_unknown` case — we can prove we are behind without being able to count by
 *  how much. Absent on older servers. */
export interface BranchStanding {
  state: "ahead" | "in_sync" | "behind" | "behind_unknown" | "no_remote" | "no_remote_base" | "unknown";
  ahead: number | null;
  behind: number | null;
  base: string | null;
}

export interface BranchRef {
  name: string;
  merged: boolean;
  protected: boolean;
}

/** One commit on the project branch ahead of the base (A2 commit-picker). */
export interface CommitRef {
  sha: string;
  short: string;
  subject: string;
  author: string;
  date: string;
}

const post = (path: string, compose?: MrCompose) =>
  apiFetch(path, {
    method: "POST",
    ...(compose ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(compose) } : {}),
  }).then(json<{ opened: boolean; url: string }>);

/** A decision the SERVER derived as pending (ADR-0105). Never minted by the model: Quincy may
 *  reference an id, and the server drops any it did not derive. `actions` names UI controls, never
 *  endpoints — no url, method, or body, so nothing here can be talked into carrying a credential. */
export interface Decision {
  id: string;
  kind:
    | "gate_pending"
    | "integration_missing"
    | "mr_stuck"
    | "delivered_no_mr"
    | "backlog_health";
  /** `blocking` = delivery cannot proceed until a human acts. `standing` = nothing is broken,
   *  work is outstanding. Describes the CONDITION, not the button — every card links out. */
  tier?: "blocking" | "standing";
  title: string;
  summary: string;
  requires_admin: boolean;
  actions: { label: string; kind: string }[];
  run_id?: string;
  item_id?: number;
}

/** Whether this project can open a delivery request at all, and on which forge (ADR-0112).
 *
 *  `can_finish` answers only "could a request be opened" — an empty diff or a diverged base
 *  still refuse later. It deliberately does not promise the delivery will succeed; replacing
 *  one dishonest signal with a more confident one is not an improvement.
 *
 *  Optional throughout, so an older server that lacks the endpoint degrades to today's
 *  behaviour rather than blanking the page. */
export interface DeliveryCapability {
  provider: "gitlab" | "github" | "unknown";
  can_finish: boolean;
  reason: string | null;
  detail: string;
  /** A limit that holds even when the project CAN finish — distinct from `detail`, which
   *  explains why it cannot. Optional: absent on a server predating ADR-0114. */
  note?: string;
  /** Per-item requests are GitLab-only: its item MRs are stacked, and reproducing that on a
   *  second forge is its own slice. Absent ⇒ assume true (the pre-ADR-0114 behaviour). */
  item_requests_supported?: boolean;
  has_gitlab_token: boolean;
  has_gitlab_api_token: boolean;
  github_app_configured?: boolean;
  has_github_connection?: boolean;
  /** F64's own bit: without `api` scope the MR poll never runs, so a project can open a
   *  merge request and still never read as delivered. */
  merge_state_readable: boolean;
}

/** One installation of the Mosaera GitHub App, as the settings panel lists them.
 *
 *  `repository_selection` is the bit an operator actually needs: `"selected"` means the App
 *  reaches only the repositories picked at install time, which is the usual reason a project
 *  that *looks* covered is not. */
export interface GitHubInstallation {
  id: number | null;
  account: string | null;
  account_type: string | null;
  avatar_url: string | null;
  repository_selection: "all" | "selected" | null;
}

export const deliveryApi = {
  /** ADR-0112 — asked before the work, not after it (#120). */
  projectDeliveryCapability: (id: string) =>
    apiFetch(`/api/projects/${id}/delivery/capability`).then(json<DeliveryCapability>),

  /** Whether this instance can deliver to GitHub at all, and where to install the App. */
  githubStatus: () =>
    apiFetch(`/api/github/status`).then(
      json<{ configured: boolean; is_admin: boolean; install_url: string }>,
    ),

  /** Where the App is installed — the Git settings panel's list, admin-only. Read-only: none
   *  of these ids is ever spent, so this does not weaken ADR-0114's "never trust an
   *  installation id you were handed" rule. Delivery still asks about `source_repo`. */
  githubInstallations: () =>
    adminFetch(`/api/github/installations`).then(
      json<{
        configured: boolean;
        installations: GitHubInstallation[];
        install_url: string;
        error: string | null;
      }>,
    ),

  /** The manifest + state the browser POSTs to GitHub to register the App (ADR-0121). Returns
   *  nothing secret — nothing secret exists yet, which is the point of the flow. */
  githubSetupManifest: () =>
    adminFetch(`/api/github/setup/manifest`).then(
      json<{ url: string; manifest: string; redirect_uri: string }>,
    ),

  /** Store an App the operator registered themselves — the escape hatch beside the one-click
   *  flow. The server rejects an unreadable PEM here rather than at the first connect. */
  githubSetupManual: (body: {
    app_id: string;
    private_key: string;
    slug: string;
    client_id: string;
    client_secret: string;
  }) =>
    adminFetch(`/api/github/setup/manual`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ ok: boolean }>),

  /** Store the OAuth App that creates repositories (ADR-0120 A2). Separate from the GitHub App:
   *  GitHub refuses App tokens on its repository-creation endpoints. */
  githubSetupOAuthApp: (body: { client_id: string; client_secret: string }) =>
    adminFetch(`/api/github/oauth-app`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ ok: boolean }>),

  /** Whether "Create repository" can be offered (ADR-0120). Separate from `githubStatus`
   *  because the App can be registered for delivery without its user-authorization pair set. */
  githubRepoStatus: () =>
    apiFetch(`/api/github/repo/status`).then(
      json<{ configured: boolean; is_admin: boolean; host: string }>,
    ),

  /** ADR-0114 — resolve which App installation owns this project's repo. Unlike the GitLab
   *  Connect this is a plain POST, not a full-page OAuth redirect: nothing that comes back
   *  from a redirect is trusted, so there is no handshake to ride. */
  connectGithub: (id: string) =>
    adminFetch(`/api/projects/${id}/github/connect`, { method: "POST" }).then(
      json<{ connected: boolean; owner_repo: string }>,
    ),

  projectDiff: (id: string) =>
    apiFetch(`/api/projects/${id}/diff`).then(
      json<{
        base: string;
        diff: string;
        has_changes: boolean;
        files: string[];
        stats?: { path: string; additions: number | null; deletions: number | null }[];
        remote_synced?: boolean | null;
        standing?: BranchStanding;
      }>,
    ),

  // ADR-0102: `items` is the per-item MR states (absent on older servers).
  projectMrStatus: (id: string) =>
    apiFetch(`/api/projects/${id}/mr-status`).then(
      json<{
        state: string | null;
        url: string;
        items?: { id: number; state: string | null; url: string }[];
      }>,
    ),

  /** Open a project MR (ADR-0102 slice O); `compose` (ADR-0103) edits it before sending. */
  mergeProject: (id: string, compose?: MrCompose) => post(`/api/projects/${id}/merge`, compose),

  /** Open one item's stacked MR; `compose` (ADR-0103) edits it before sending. */
  openItemMr: (id: string, itemId: number, compose?: MrCompose) =>
    post(`/api/projects/${id}/items/${itemId}/open-mr`, compose),

  /** GitLab's LIVE mergeability verdict for one item's MR, read at the moment the operator is
   *  asked (ADR-0102 amendment). Deliberately not polled onto the row: a verdict from the last
   *  poll describes the MR as it WAS, and the operator is about to act on it as it IS.
   *  `adminFetch` because merging is admin-gated, and asking spends the api token. */
  itemMergeReadiness: (id: string, itemId: number) =>
    adminFetch(`/api/projects/${id}/items/${itemId}/merge-readiness`).then(
      json<{
        status: string;
        sha: string;
        source_branch: string;
        target_branch: string;
        web_url: string;
        error: string | null;
      }>,
    ),

  /** Merge one item's MR, or queue it behind the pipeline. THE only call in this SPA that changes
   *  a real repository's target branch. `sha` is the head the operator was shown, so a branch that
   *  moved since the readiness read is refused by GitLab rather than merged unseen. */
  mergeItemMr: (id: string, itemId: number, body: { when_pipeline_succeeds?: boolean; sha?: string }) =>
    adminFetch(`/api/projects/${id}/items/${itemId}/merge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ merged: boolean; queued: boolean }>),

  /** Does the delivered tree work for someone who CLONES it? (#104) Read-only and offline: the
   *  gate proves the code works under the SANDBOX's conditions, and this answers the other
   *  question — the one a stakeholder actually reads the gate as answering. */
  cleanCheck: (id: string) =>
    apiFetch(`/api/projects/${id}/clean-check`).then(
      json<{
        status: "passed" | "failed" | "not_checked";
        findings: string[];
        steps: { step: string; result: string }[];
        not_checked_reason: string;
      }>,
    ),

  /** The project's branches — read from the local clone (A1), no token needed. */
  /** `source` says where the list came from: "gitlab" (real, includes merge state) or "clone"
   *  (degraded — the project clone never holds mosaera/* branches, so the list is partial). */
  listBranches: (id: string) =>
    apiFetch(`/api/projects/${id}/branches`).then(
      json<{ branches: BranchRef[]; source?: "gitlab" | "clone" }>,
    ),

  /** Commits on the project branch ahead of the base (A2 commit-picker). */
  listCommits: (id: string) =>
    apiFetch(`/api/projects/${id}/commits`).then(json<{ commits: CommitRef[] }>),

  /** Delete merged item branches (ADR-0103 Phase 4) — rides write_repository. */
  pruneMergedBranches: (id: string) =>
    apiFetch(`/api/projects/${id}/branches/prune`, { method: "POST" }).then(
      json<{ pruned: string[] }>,
    ),

  /** Delete one remote branch (A3) — write_repository, guarded server-side. */
  /** Repoint a stuck item MR (0028). Needs the project's api-scoped token. */
  retargetItemMr: (id: string, itemId: number, targetBranch: string) =>
    apiFetch(`/api/projects/${id}/items/${itemId}/retarget`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_branch: targetBranch }),
    }).then(json<{ opened: boolean; url: string }>),

  /** What is waiting on a human for this project (ADR-0105) — derived server-side on every
   *  call, so a decision disappears once its underlying control resolves. */
  projectDecisions: (id: string) =>
    apiFetch(`/api/projects/${id}/decisions`).then(json<{ decisions: Decision[] }>),

  /** Close or reopen a merge request — the half of the lifecycle the product never had. Needs
   *  the project's api-scoped token. Closing destroys nothing; reopen undoes it. */
  setItemMrState: (id: string, itemId: number, action: "close" | "reopen") =>
    apiFetch(`/api/projects/${id}/items/${itemId}/mr-state`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    }).then(json<{ opened: boolean; url: string }>),

  setProjectMrState: (id: string, action: "close" | "reopen") =>
    apiFetch(`/api/projects/${id}/mr-state`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    }).then(json<{ opened: boolean; url: string }>),

  deleteBranch: (id: string, branch: string) =>
    apiFetch(`/api/projects/${id}/branches/${encodeURIComponent(branch)}/delete`, {
      method: "POST",
    }).then(json<{ deleted: string }>),

  /** Whether to offer "Connect with GitLab" (ADR-0104): OAuth configured + caller is admin; `host`
   *  is the configured GitLab (self-hosted first). The connect itself is a full-page redirect to
   *  `/api/oauth/gitlab/start` (a browser handshake), not a fetch. */
  gitlabOauthStatus: () =>
    apiFetch(`/api/oauth/gitlab/status`).then(
      json<{ configured: boolean; is_admin: boolean; host: string }>,
    ),
};
