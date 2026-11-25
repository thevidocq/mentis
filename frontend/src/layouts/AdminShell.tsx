import { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { ROLE_LABEL } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Icon, IconName } from "../components/Icon";
import { Brand } from "../components/Logo";

export interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  soon?: boolean;
}

export function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";
}

export function AdminShell({ eyebrow, title, nav, children }: { eyebrow: string; title: string; nav: NavItem[]; children: ReactNode }) {
  const { user } = useAuth();
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><Brand /></div>
        <div className="sidebar-block">
          <div className="eyebrow">{eyebrow}</div>
          <strong>{title}</strong>
        </div>
        <nav className="nav" aria-label={`${eyebrow} menu`}>
          {nav.map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon name={item.icon} />
              {item.label}
              {item.soon && <span className="soon">soon</span>}
            </NavLink>
          ))}
        </nav>
        {user && (
          <Link to="/account" className="user-link">
            <div className="avatar">{initials(user.full_name)}</div>
            <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
              <span style={{ fontWeight: 600 }}>{user.full_name}</span>
              <span className="muted small">{ROLE_LABEL[user.role]} · Account</span>
            </div>
            <Icon name="chevronRight" />
          </Link>
        )}
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

export function PageHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="page-head">
      <h1>{title}</h1>
      {children}
    </header>
  );
}

export const PLATFORM_NAV: NavItem[] = [
  { to: "/admin/tenants", label: "Tenants", icon: "tenants" },
  { to: "/admin/users", label: "Users", icon: "users" },
  { to: "/admin/general", label: "General documentation", icon: "book" },
  { to: "/admin/ai", label: "AI providers", icon: "chip" },
  { to: "/admin/embedding", label: "Embedding and Qdrant", icon: "database" },
  { to: "/admin/smtp", label: "Email (SMTP)", icon: "mail" },
  { to: "/admin/retention", label: "Retention", icon: "clock", soon: true },
  { to: "/admin/status", label: "Service status", icon: "pulse" },
  { to: "/admin/logs", label: "Logs", icon: "list", soon: true },
  { to: "/chat", label: "Chat", icon: "chat" },
  { to: "/help", label: "Help", icon: "help" },
];

export const TENANT_NAV: NavItem[] = [
  { to: "/tenant/documents", label: "Documents", icon: "file" },
  { to: "/tenant/integrations", label: "Integrations", icon: "link", soon: true },
  { to: "/tenant/llm", label: "LLM", icon: "brain" },
  { to: "/tenant/users", label: "Users", icon: "users" },
  { to: "/tenant/settings", label: "Settings", icon: "sliders" },
  { to: "/chat", label: "Chat", icon: "chat" },
  { to: "/help", label: "Help", icon: "help" },
];
