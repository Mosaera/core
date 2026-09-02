// Session-cookie auth for the Mosaera API.
//
// After login the server sets an HttpOnly session cookie (see routes/auth.py).
// The browser attaches it automatically to every same-origin request — including
// EventSource (SSE) and <img>/<a download> URLs — so the SPA carries NO token
// itself (nothing for XSS to read, nothing in the URL). The shared MOSAERA_API_TOKEN
// still works as a service credential for non-browser clients (CI, the harness).
//
// `withToken`/`authHeader` are retained as no-op shims so their many call sites
// (SSE + media URLs) keep working unchanged now that cookies do the carrying.

const listeners = new Set<() => void>();

/** Subscribe to auth changes (a 401 anywhere → the AuthProvider re-probes). */
export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function notify(): void {
  listeners.forEach((fn) => fn());
}

/** No-op: same-origin cookies are attached to header-less transports (EventSource,
 *  <img src>, <a download>) automatically. Kept so call sites don't change. */
export function withToken(url: string): string {
  return url;
}

/** Retained shim — session identity rides the cookie, not a header. */
export function authHeader(): Record<string, string> {
  return {};
}

/** fetch() carrying the session cookie. A 401 means the session is missing/expired,
 *  so notify subscribers — the AuthProvider re-probes and drops to the login screen. */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(input, { ...init, credentials: "same-origin" });
  if (res.status === 401) notify();
  return res;
}

// --- auth flow (plain fetch: a bad-credential 401 here must NOT trigger the global
// session-expiry notify above; the caller handles the status inline) ---

const jsonInit = (body: unknown): RequestInit => ({
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export interface AuthUser {
  id: number;
  username: string;
  is_admin: boolean;
}

export interface AuthStatus {
  users_supported: boolean;
  /** A database, and no accounts in it. The SPA cannot ACT on this — creating the first
   *  administrator is `mosaera-setup`'s job, in a terminal (ADR-0116) — but it says so instead
   *  of showing a login form nothing can get through. */
  needs_setup: boolean;
  auth_required: boolean;
  user: AuthUser | null;
}

export const authApi = {
  status: (): Promise<AuthStatus> =>
    fetch("/api/auth/status", { credentials: "same-origin" }).then((r) => r.json()),
  login: (username: string, password: string): Promise<Response> =>
    fetch("/api/auth/login", jsonInit({ username, password })),
  logout: (): Promise<Response> =>
    fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" }).finally(notify),
};
