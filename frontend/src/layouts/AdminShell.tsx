import { ReactNode, useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Icon, IconName } from "../components/Icon";
import { Brand } from "../components/Logo";
import { SidebarFooter } from "./SidebarFooter";

export interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  soon?: boolean;
}

export { initials } from "./SidebarFooter";

export function AdminShell({ eyebrow, title, titleControl, nav, children }: {
  eyebrow: string; title: string; titleControl?: ReactNode; nav: NavItem[]; children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]); // close the drawer after navigating
  return (
    <div className={`shell${open ? " drawer-open" : ""}`}>
      <MobileBar title={title} onMenu={() => setOpen(true)} />
      <div className="drawer-backdrop" onClick={() => setOpen(false)} aria-hidden="true" />
      <aside className="sidebar" aria-label="Menu">
        <div className="brand">
          <Brand />
          <button className="icon-btn drawer-close" style={{ border: 0 }} aria-label="Close menu" onClick={() => setOpen(false)}><Icon name="x" /></button>
        </div>
        <div className="sidebar-block">
          <div className="eyebrow">{eyebrow}</div>
          {titleControl ?? <strong>{title}</strong>}
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
        <SidebarFooter />
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

/** Top bar shown only on small screens: menu button, logo and the page title. */
export function MobileBar({ title, onMenu, right }: { title: string; onMenu: () => void; right?: ReactNode }) {
  return (
    <header className="mobile-bar">
      <button className="icon-btn" style={{ border: 0 }} aria-label="Open menu" onClick={onMenu}><Icon name="menu" size={20} /></button>
      <span className="mobile-title">{title}</span>
      {right}
    </header>
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
  { to: "/admin/ai", label: "AI providers", icon: "chip" },
  { to: "/admin/usage", label: "LLM usage", icon: "bars" },
  { to: "/admin/embedding", label: "Embedding and Qdrant", icon: "database" },
  { to: "/admin/smtp", label: "Email (SMTP)", icon: "mail" },
  { to: "/admin/retention", label: "Retention", icon: "clock" },
  { to: "/admin/status", label: "Service status", icon: "pulse" },
  { to: "/admin/logs", label: "Logs", icon: "list" },
  { to: "/admin/configuration", label: "Backup and configuration", icon: "archive" },
];

export const TENANT_NAV: NavItem[] = [
  { to: "/tenant/documents", label: "Documents", icon: "file" },
  { to: "/tenant/integrations", label: "Integrations", icon: "link", soon: true },
  { to: "/tenant/llm", label: "LLM", icon: "brain" },
  { to: "/tenant/users", label: "Users", icon: "users" },
  { to: "/tenant/settings", label: "Settings", icon: "sliders" },
  { to: "/chat", label: "Chat", icon: "chat" },
];
