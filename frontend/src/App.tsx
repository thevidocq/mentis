import { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { Role } from "./api/types";
import { homePath, useAuth } from "./auth/AuthContext";
import { AdminShell, PLATFORM_NAV, TENANT_NAV } from "./layouts/AdminShell";
import { Account } from "./pages/Account";
import { AcceptInvite } from "./pages/AcceptInvite";
import { ChatHome } from "./pages/ChatHome";
import { Login } from "./pages/Login";
import { Placeholder } from "./pages/Placeholder";
import { Setup } from "./pages/Setup";
import { ServiceStatus } from "./pages/platform/ServiceStatus";
import { SmtpSettings } from "./pages/platform/SmtpSettings";
import { Tenants } from "./pages/platform/Tenants";
import { Users } from "./pages/Users";
import { TenantSettings } from "./pages/tenant/TenantSettings";

function RequireRole({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (roles && !roles.includes(user.role)) return <Navigate to={homePath(user)} replace />;
  return <>{children}</>;
}

const soon = (title: string, what: string) => <Placeholder title={title} text={`${what} arrives in a later 0.1.0 block.`} />;

function PlatformArea() {
  return (
    <AdminShell eyebrow="Administration" title="Platform" nav={PLATFORM_NAV}>
      <Routes>
        <Route path="tenants" element={<Tenants />} />
        <Route path="users" element={<Users />} />
        <Route path="smtp" element={<SmtpSettings />} />
        <Route path="status" element={<ServiceStatus />} />
        <Route path="general" element={soon("General documentation", "Uploading documentation for the General tenant")} />
        <Route path="ai" element={soon("AI providers", "LLM provider configuration")} />
        <Route path="embedding" element={soon("Embedding and Qdrant", "Embedding configuration")} />
        <Route path="retention" element={soon("Retention", "Retention settings")} />
        <Route path="logs" element={soon("Logs", "The Logs section")} />
        <Route path="*" element={<Navigate to="tenants" replace />} />
      </Routes>
    </AdminShell>
  );
}

function TenantArea() {
  const { user } = useAuth();
  return (
    <AdminShell eyebrow="Tenant" title={user?.tenant_name ?? "My customer"} nav={TENANT_NAV}>
      <Routes>
        <Route path="users" element={<Users />} />
        <Route path="settings" element={<TenantSettings />} />
        <Route path="documents" element={soon("Documents", "Document upload, versions and preview")} />
        <Route path="integrations" element={soon("Integrations", "Ticketing, EDR and SIEM integrations")} />
        <Route path="llm" element={soon("LLM", "Choosing the tenant's LLM")} />
        <Route path="*" element={<Navigate to="documents" replace />} />
      </Routes>
    </AdminShell>
  );
}

export function App() {
  const { user, loading, needsSetup } = useAuth();
  if (loading) return null;
  if (needsSetup) {
    return (
      <Routes>
        <Route path="*" element={<Setup />} />
      </Routes>
    );
  }
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to={homePath(user)} replace /> : <Login />} />
      <Route path="/invite/:token" element={<AcceptInvite />} />
      <Route path="/account" element={<RequireRole><Account /></RequireRole>} />
      <Route path="/admin/*" element={<RequireRole roles={["super_admin"]}><PlatformArea /></RequireRole>} />
      <Route path="/tenant/*" element={<RequireRole roles={["tenant_admin"]}><TenantArea /></RequireRole>} />
      <Route path="/chat" element={<RequireRole><ChatHome /></RequireRole>} />
      <Route path="*" element={user ? <Navigate to={homePath(user)} replace /> : <Navigate to="/login" replace />} />
    </Routes>
  );
}
