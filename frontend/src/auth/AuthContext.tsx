import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Theme, User } from "../api/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  needsSetup: boolean;
  webSetup: boolean;
  refresh: () => Promise<void>;
  setUser: (u: User | null) => void;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function applyTheme(theme: Theme | undefined) {
  const t = theme ?? (localStorage.getItem("mentis-theme") as Theme | null) ?? "dark";
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("mentis-theme", t); } catch { /* storage unavailable */ }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [webSetup, setWebSetup] = useState(false);

  const setUser = useCallback((u: User | null) => {
    setUserState(u);
    if (u) applyTheme(u.preferences?.theme);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const status = await api<{ needs_setup: boolean; web_setup?: boolean }>("/setup/status");
      setNeedsSetup(status.needs_setup);
      setWebSetup(!!status.web_setup);
      setUser(status.needs_setup ? null : await api<User>("/auth/me").catch(() => null));
    } finally {
      setLoading(false);
    }
  }, [setUser]);

  const logout = useCallback(async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    setUserState(null);
  }, []);

  useEffect(() => {
    applyTheme(undefined);
    void refresh();
  }, [refresh]);

  return <Ctx.Provider value={{ user, loading, needsSetup, webSetup, refresh, setUser, logout }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export function homePath(user: User): string {
  if (user.role === "super_admin") return "/admin/tenants";
  if (user.role === "tenant_admin") return "/tenant/documents";
  return "/chat";
}
