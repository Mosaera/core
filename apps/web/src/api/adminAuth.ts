// Admin actions (config/secret/user writes) are authorized by the logged-in user's
// session (is_admin) — enforced server-side by the API's admin gate — or, for
// non-browser/service callers, by MOSAERA_ADMIN_TOKEN. In the browser the session
// cookie carries identity, so an admin action is just a normal authenticated fetch.
// `adminFetch` stays a distinct export so config/secret call sites read as admin
// actions and can gain admin-specific handling later without touching them all.

export { apiFetch as adminFetch } from "./auth";
