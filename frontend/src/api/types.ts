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

export type VersionStatus = "queued" | "processing" | "ready" | "failed";
export type Approval = "not_required" | "pending" | "approved" | "rejected";

export interface DocVersion {
  id: string;
  version: number;
  original_filename: string;
  file_type: "pdf" | "docx" | "pptx" | "xlsx";
  size_bytes: number;
  status: VersionStatus;
  approval: Approval;
  is_active: boolean;
  note: string | null;
  error: string | null;
  stats: { pages?: number; ocr_pages?: number; tables?: number; empty_pages?: number; low_confidence_pages?: number; chars?: number; warnings?: string[] };
  uploaded_at: string;
  processed_at: string | null;
}

export interface DocSummary {
  id: string;
  name: string;
  created_at: string;
  active: DocVersion | null;
  latest: DocVersion;
  versions: number;
}

export interface DocPage {
  index: number;
  kind: "page" | "section" | "slide" | "sheet";
  label: string;
  text: string;
  method: "native" | "ocr";
  ocr_confidence: number | null;
  tables: number;
  has_image: boolean;
  flags: string[];
}
