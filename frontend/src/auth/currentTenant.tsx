// The customer a tenant admin is working on, when it administers several. Kept per browser.

import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { TenantRef } from "../api/types";
import { useAuth } from "./AuthContext";

const KEY = "mentis-current-tenant";

interface CurrentTenant {
  tenants: TenantRef[];
  current: TenantRef | null;
  select: (id: string) => void;
  recent: string[]; // last customers chosen, most recent first
}

const Ctx = createContext<CurrentTenant>({ tenants: [], current: null, select: () => undefined, recent: [] });
const RECENT_KEY = "mentis-recent-tenants";

function storedRecent(): string[] {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]") as string[]; } catch { return []; }
}

function stored(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

export function CurrentTenantProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const tenants = useMemo(() => user?.tenants ?? [], [user]);
  const [id, setId] = useState<string | null>(stored);
  const [recent, setRecent] = useState<string[]>(storedRecent);

  useEffect(() => {
    // Fall back to the first tenant when the stored one is not (or no longer) the user's.
    if (tenants.length && !tenants.some((t) => t.id === id)) setId(tenants[0].id);
  }, [tenants, id]);

  const select = useCallback((next: string) => {
    setId(next);
    setRecent((r) => {
      const list = [next, ...r.filter((x) => x !== next)].slice(0, 5);
      try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch { /* storage unavailable */ }
      return list;
    });
    try { localStorage.setItem(KEY, next); } catch { /* storage unavailable */ }
  }, []);

  const current = tenants.find((t) => t.id === id) ?? tenants[0] ?? null;
  return <Ctx.Provider value={{ tenants, current, select, recent }}>{children}</Ctx.Provider>;
}

export function useCurrentTenant(): CurrentTenant {
  return useContext(Ctx);
}
