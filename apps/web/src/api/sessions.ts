// PM chat sessions (issue #30): per-project conversation threads. Kept in its own module
// (not client.ts, which is grandfathered over the size ceiling) — the message read/write
// helpers stay in client.ts; this owns the session lifecycle surface.

import { apiFetch } from "./auth";

/** One PM conversation thread within a project. History is scoped to a session; project
 *  knowledge (brief/backlog/runs/context) is shared across a project's sessions. */
export interface PmSession {
  id: string;
  project_id: string;
  title: string; // "" until the first user turn auto-names it
  created_at: string | null;
  updated_at: string | null;
  message_count: number;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail}` : ""}`);
  }
  return res.json() as Promise<T>;
}

export const sessionsApi = {
  list: (projectId: string) =>
    apiFetch(
      `/api/projects/${projectId}/sessions`,
    ).then(json<{ sessions: PmSession[] }>),

  create: (projectId: string, title = "") =>
    apiFetch(`/api/projects/${projectId}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }).then(json<PmSession>),

  patch: (projectId: string, sessionId: string, patch: { title?: string; archived?: boolean }) =>
    apiFetch(`/api/projects/${projectId}/sessions/${sessionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then(json<PmSession>),
};
