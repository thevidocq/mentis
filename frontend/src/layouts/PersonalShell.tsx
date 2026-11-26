import { ReactNode } from "react";
import { useAuth } from "../auth/AuthContext";
import { useCurrentTenant } from "../auth/currentTenant";
import { AdminShell, NavItem, PLATFORM_NAV, TENANT_NAV } from "./AdminShell";

const ANALYST_NAV: NavItem[] = [{ to: "/chat", label: "Chat", icon: "chat" }];

/** Pages of the signed-in user (Account): the same menu as the rest of their area, Log out included. */
export function PersonalShell({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const { current } = useCurrentTenant();
  if (user?.role === "super_admin") return <AdminShell eyebrow="Administration" title="Platform" nav={PLATFORM_NAV}>{children}</AdminShell>;
  if (user?.role === "tenant_admin") return <AdminShell eyebrow="Customer" title={current?.name ?? "My customer"} nav={TENANT_NAV}>{children}</AdminShell>;
  return <AdminShell eyebrow="Mentis" title="Analyst" nav={ANALYST_NAV}>{children}</AdminShell>;
}
