import { apiFetch } from "./auth";

/** A key as the server will ever describe it: never the secret, never its hash. The plaintext
 *  exists once, in the response to `createApiKey`, and is not recoverable afterwards. */
export interface ApiKeyRow {
  id: number;
  name: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const detail = await r
      .json()
      .then((b: { detail?: string }) => b?.detail)
      .catch(() => undefined);
    throw new Error(detail ?? `${r.status} ${r.statusText}`);
  }
  return (await r.json()) as T;
}

/** Per-user API keys (ADR-0127).
 *
 *  Every call is `apiFetch`, NOT `adminFetch` — deliberately. A key is not an admin credential
 *  and managing one is not an admin action: these endpoints need a SESSION, which is also the
 *  mechanism that stops a key minting another key. Routing them through `adminFetch` would both
 *  lock members out of their own keys and misdescribe what the feature is.
 *
 *  Its own module rather than `client.ts` because that file is a grandfathered god-file under a
 *  shrink-only ratchet; adding to it is the one thing the guard forbids.
 */
export const keysApi = {
  list: () => apiFetch("/api/keys").then(json<{ keys: ApiKeyRow[] }>),

  create: (name: string) =>
    apiFetch("/api/keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).then(json<ApiKeyRow & { key: string }>),

  revoke: (id: number) =>
    apiFetch(`/api/keys/${id}`, { method: "DELETE" }).then(json<{ revoked: boolean }>),
};
