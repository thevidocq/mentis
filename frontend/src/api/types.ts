export type Role = "super_admin" | "tenant_admin" | "analyst";
export type Theme = "light" | "medium" | "dark";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  tenant_id: string | null;
  totp_enabled: boolean;
  preferences: { theme?: Theme };
  tenant_name?: string | null;
}

export interface AdminUser extends User {
  is_active: boolean;
  locked: boolean;
}

export interface TenantSettings {
  include_general: boolean;
  require_approval: boolean;
  suggested_followups: boolean;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  is_global: boolean;
  status: "active" | "onboarding" | "disabled";
  settings: TenantSettings;
  users: number;
}

export interface Invitation {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  tenant_id: string | null;
  expires_at: string;
}

export interface InvitationCreated extends Invitation {
  email_sent: boolean;
  invite_url: string | null;
}

export interface Smtp {
  host: string;
  port: number;
  security: "starttls" | "ssl" | "none";
  username: string;
  from_address: string;
  password_set: boolean;
  configured: boolean;
}

export const ROLE_LABEL: Record<Role, string> = {
  super_admin: "Super-admin",
  tenant_admin: "Tenant admin",
  analyst: "Analyst",
};
