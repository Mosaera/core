/* The project-proof aggregate (ADR-0109), split out of client.ts — that file sits on a
   shrink-only ratchet and is grandfathered at its ceiling, so new surface goes beside it rather
   than into it. Spread into the `api` object in client.ts, so call sites use `api.projectProof`. */

import { apiFetch } from "./auth";
import { json } from "./client";

export interface ProofAxisCounts {
  key: string;
  label: string;
  note: string;
  proven: number;
  failed: number;
  /** Deliveries with nothing recorded for this axis. Never counted as proven OR failed. */
  unknown: number;
  /** proven + failed — the honest denominator, not the delivered count (ADR-0109 rule 5). */
  measured: number;
}

export interface ProjectProofResponse {
  delivered: number;
  axes: ProofAxisCounts[];
  /** ADR-0109 rule 4: every delivery appears in exactly one of these, so the summary can be
   *  reconciled against the receipts by hand. */
  sources: { receipts_read: string[]; receipts_unreadable: string[] };
}

export const proofApi = {
  /** Receipt-backed, derived per request, and it discloses the receipts it read. */
  projectProof: (projectId: string) =>
    apiFetch(`/api/projects/${projectId}/proof`).then(json<ProjectProofResponse>),
};
