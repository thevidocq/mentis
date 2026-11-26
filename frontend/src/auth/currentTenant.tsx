// The customer a tenant admin is working on, when it administers several. Kept per browser and user.

import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { TenantRef } from "../api/types";
import { useAuth } from "./AuthContext";


interface CurrentTenant {
  tenants: TenantRef[];
  current: TenantRef | null;
  select: (id: string) => void;
  recent: string[]; // last customers chosen, most recent first
}

const Ctx = createContext<CurrentTenant>({ tenants: [], current: null, select: () => undefined, recent: [] });

// Keys are per user: on a shared PC the next user never sees (or acts on) the previous one's choice.
const keyOf = (userId: string) => `mentis-current-tenant:${userId}`;
const recentKeyOf = (userId: string) => `mentis-recent-tenants:${userId}`;
// Up to 0.3.1 the keys were shared by every user of the browser: remove them.
try { localStorage.removeItem("mentis-current-tenant"); localStorage.removeItem("mentis-recent-tenants"); } catch { /* storage unavailable */ }

function storedRecent(userId: string | undefined): string[] {
  if (!userId) return [];
  try {
    const v: unknown = JSON.parse(localStorage.getItem(recentKeyOf(userId)) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch { return []; }
}

function stored(userId: string | undefined): string | null {
  if (!userId) return null;
  try { return localStorage.getItem(keyOf(userId)); } catch { return null; }
}

export function CurrentTenantProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const userId = user?.id;
  const tenants = useMemo(() => user?.tenants ?? [], [user]);
  const [owner, setOwner] = useState(userId);
  const [id, setId] = useState<string | null>(() => stored(userId));
  const [recent, setRecent] = useState<string[]>(() => storedRecent(userId));
  // Another user signed in (or the session ended) without a page reload: drop the previous choice.
  if (owner !== userId) {
    setOwner(userId);
    setId(stored(userId));
    setRecent(storedRecent(userId));
  }

  useEffect(() => {
    // Fall back to the first tenant when the stored one is not (or no longer) the user's.
    if (tenants.length && !tenants.some((t) => t.id === id)) setId(tenants[0].id);
  }, [tenants, id]);

  const select = useCallback((next: string) => {
    if (!userId) return;
    setId(next);
    setRecent((r) => {
      const list = [next, ...r.filter((x) => x !== next)].slice(0, 5);
      try { localStorage.setItem(recentKeyOf(userId), JSON.stringify(list)); } catch { /* storage unavailable */ }
      return list;
    });
    try { localStorage.setItem(keyOf(userId), next); } catch { /* storage unavailable */ }
  }, [userId]);

  const current = tenants.find((t) => t.id === id) ?? tenants[0] ?? null;
  return <Ctx.Provider value={{ tenants, current, select, recent }}>{children}</Ctx.Provider>;
}

export function useCurrentTenant(): CurrentTenant {
  return useContext(Ctx);
}
