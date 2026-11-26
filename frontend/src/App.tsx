import { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import type { Role } from "./api/types";
import { homePath, useAuth } from "./auth/AuthContext";
import { useCurrentTenant } from "./auth/currentTenant";
import { AdminShell, PLATFORM_NAV, TENANT_NAV } from "./layouts/AdminShell";
import { CustomerSelect } from "./components/CustomerSelect";
import { Account } from "./pages/Account";
import { AcceptInvite } from "./pages/AcceptInvite";
import { ForgotPassword, ResetPassword } from "./pages/PasswordReset";
import { ChatPage } from "./pages/chat/ChatPage";
import { SharedChatPage } from "./pages/chat/SharedChatPage";
import { Help } from "./pages/Help";
import { TenantDocuments, TenantPreview } from "./pages/documents/routes";
import { Login } from "./pages/Login";
import { Setup } from "./pages/Setup";
import { AiProviders } from "./pages/platform/AiProviders";
import { Configuration } from "./pages/platform/Configuration";
import { Logs } from "./pages/platform/Logs";
import { RetentionSettings } from "./pages/platform/Retention";
import { Usage } from "./pages/platform/Usage";
import { EmbeddingSettings } from "./pages/platform/EmbeddingSettings";
import { ServiceStatus } from "./pages/platform/ServiceStatus";
import { SmtpSettings } from "./pages/platform/SmtpSettings";
import { Tenants } from "./pages/platform/Tenants";
import { Users } from "./pages/Users";
import { PlatformIntegrations } from "./pages/integrations/PlatformIntegrations";
import { TenantIntegrations } from "./pages/integrations/TenantIntegrations";
import { TenantLlm } from "./pages/tenant/TenantLlm";
import { TenantSettings } from "./pages/tenant/TenantSettings";

function RequireRole({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (roles && !roles.includes(user.role)) return <Navigate to={homePath(user)} replace />;
  return <>{children}</>;
}

function PlatformArea() {
  return (
    <AdminShell eyebrow="Administration" title="Platform" nav={PLATFORM_NAV}>
      <Routes>
        <Route path="tenants" element={<Tenants />} />
        <Route path="users" element={<Users />} />
        <Route path="smtp" element={<SmtpSettings />} />
        <Route path="status" element={<ServiceStatus />} />
        <Route path="ai" element={<AiProviders />} />
        <Route path="integrations" element={<PlatformIntegrations />} />
        <Route path="embedding" element={<EmbeddingSettings />} />
        <Route path="usage" element={<Usage />} />
        <Route path="retention" element={<RetentionSettings />} />
        <Route path="logs" element={<Logs />} />
        <Route path="configuration" element={<Configuration />} />
        <Route path="*" element={<Navigate to="tenants" replace />} />
      </Routes>
    </AdminShell>
  );
}

function TenantArea() {
  const { current, tenants, select, recent } = useCurrentTenant();
  const navigate = useNavigate();
  const switcher = tenants.length > 1 ? (
    <CustomerSelect tenants={tenants} current={current} recent={recent}
      onSelect={(id) => { select(id); navigate("/tenant/documents"); }} />
  ) : undefined;
  return (
    <AdminShell eyebrow={tenants.length > 1 ? `Tenant · ${tenants.length}` : "Tenant"} title={current?.name ?? "My customer"} titleControl={switcher} nav={TENANT_NAV}>
      <Routes key={current?.id}>
        <Route path="users" element={<Users />} />
        <Route path="settings" element={<TenantSettings />} />
        <Route path="documents" element={<TenantDocuments />} />
        <Route path="documents/preview/:versionId" element={<TenantPreview />} />
        <Route path="integrations" element={<TenantIntegrations />} />
        <Route path="llm" element={<TenantLlm />} />
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
      <Route path="/forgot" element={user ? <Navigate to={homePath(user)} replace /> : <ForgotPassword />} />
      <Route path="/reset/:token" element={<ResetPassword />} />
      <Route path="/account" element={<RequireRole><Account /></RequireRole>} />
      <Route path="/help" element={<RequireRole><Help /></RequireRole>} />
      <Route path="/admin/*" element={<RequireRole roles={["super_admin"]}><PlatformArea /></RequireRole>} />
      <Route path="/tenant/*" element={<RequireRole roles={["tenant_admin"]}><TenantArea /></RequireRole>} />
      <Route path="/chat" element={<RequireRole roles={["tenant_admin", "analyst"]}><ChatPage /></RequireRole>} />
      <Route path="/shared/:token" element={<RequireRole roles={["tenant_admin", "analyst"]}><SharedChatPage /></RequireRole>} />
      <Route path="/chat/:chatId" element={<RequireRole roles={["tenant_admin", "analyst"]}><ChatPage /></RequireRole>} />
      <Route path="*" element={user ? <Navigate to={homePath(user)} replace /> : <Navigate to="/login" replace />} />
    </Routes>
  );
}
