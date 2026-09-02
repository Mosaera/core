import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { authApi, subscribe, type AuthStatus, type AuthUser } from "./auth";

interface AuthState {
  loading: boolean;
  status: AuthStatus | null;
  user: AuthUser | null;
  isAdmin: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

/** Holds the session identity for the whole app. Probes /api/auth/status once,
 *  re-probes whenever a request 401s (session expired) or after login/logout. */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setStatus(await authApi.status());
    } catch {
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    // A 401 anywhere (see apiFetch) → the session lapsed; re-probe to re-gate.
    return subscribe(() => void refresh());
  }, [refresh]);

  const logout = useCallback(async () => {
    await authApi.logout();
    await refresh();
  }, [refresh]);

  const user = status?.user ?? null;
  return (
    <AuthContext.Provider
      value={{ loading, status, user, isAdmin: !!user?.is_admin, refresh, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
