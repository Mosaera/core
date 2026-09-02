import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Decision } from "../api/delivery";
import { liveDecisions } from "../lib/decisionAck";

/** ONE query for the decision surface, shared by the Overview band and the header bell.
 *
 *  Deliberately a single key: two `useQuery` calls on `["decisions", id]` with different intervals
 *  let the last mount win the interval, and the endpoint is not free — its `mr_stuck` derivation
 *  makes a GitLab REST call per request. Sharing the key means the bell adds ZERO requests when a
 *  project page is open, and the 60s interval is the ceiling on how often that round trip happens
 *  per tab.
 *
 *  Per project, never cross-project: there is no cross-project decisions endpoint and inventing a
 *  client-side fan-out would multiply that GitLab call by the project count. */
export function useDecisions(projectId: string | undefined) {
  const query = useQuery({
    queryKey: ["decisions", projectId],
    queryFn: () => api.projectDecisions(projectId!),
    enabled: Boolean(projectId),
    refetchInterval: 60_000,
  });
  const all: Decision[] = query.data?.decisions ?? [];
  const live = projectId ? liveDecisions(projectId, all) : [];
  return {
    ...query,
    all,
    /** Blocking conditions + standing ones the operator has not dismissed. */
    live,
    blocking: live.filter((d) => d.tier !== "standing"),
    standing: live.filter((d) => d.tier === "standing"),
  };
}
