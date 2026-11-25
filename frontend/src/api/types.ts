export type Role = "super_admin" | "tenant_admin" | "analyst";
export type Theme = "light" | "medium" | "dark";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  tenants: TenantRef[]; // tenant admins and analysts: the customers they see (General included)
  all_tenants: boolean; // every customer, also future ones
  totp_enabled: boolean;
  preferences: { theme?: Theme };
}

export interface TenantRef {
  id: string;
  name: string;
  is_general?: boolean;
}

export interface AdminUser extends User {
  is_active: boolean;
  locked: boolean;
  manageable: boolean;
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
  tenants: TenantRef[];
  all_tenants: boolean;
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

// --- Chat --------------------------------------------------------------------

export interface Citation {
  n: number;
  tenant: string;
  is_general: boolean;
  document: string;
  version: number;
  page: string;
  heading: string | null;
  text: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "ok" | "not_found" | "error";
  citations: Citation[];
  followups: string[];
  tenants: string[];
  provider_name: string | null;
  model: string | null;
  latency_ms: number | null;
  feedback: 1 | -1 | null;
  created_at: string;
}

export interface ChatSummary {
  id: string;
  title: string;
  scope_tenant_id: string | null;
  scope_name: string;
  updated_at: string;
}

export interface ChatFull extends ChatSummary {
  scope_available: boolean;
  messages: ChatMessage[];
}

export interface Exchange {
  chat: ChatSummary;
  question: ChatMessage;
  answer: ChatMessage;
}

export interface ScopeOption {
  id: string | null;
  name: string;
}

// --- LLM providers -----------------------------------------------------------

export type LlmKind = "anthropic" | "openai_chat" | "openai_responses";

export interface LlmProvider {
  id: string;
  name: string;
  kind: LlmKind;
  base_url: string;
  model: string;
  api_key_set: boolean;
  options: { reasoning_effort?: string; max_tokens?: number; price_in?: number; price_out?: number };
  is_default: boolean;
  // Tenant admins receive only id, name, model and is_default.
}

export interface LlmPreset {
  label: string;
  kind: LlmKind;
  base_url: string;
  model: string;
  options: LlmProvider["options"];
}
