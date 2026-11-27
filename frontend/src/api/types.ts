export type Role = "super_admin" | "tenant_admin" | "analyst";
export type Theme = "light" | "medium" | "dark";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  tenants: TenantRef[]; // tenant admins and analysts: the customers they see, plus the General Knowledge Base (read)
  can_manage_general?: boolean; // tenant admins who manage the General Knowledge Base
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
  chat_passages: number | null; // null: platform default (Tenant.chat_passages_default)
  passage_variety: "off" | "normal" | "high";
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  is_global: boolean;
  status: "active" | "onboarding" | "disabled";
  settings: TenantSettings;
  users: number;
  chat_passages_default?: number;
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
  file_type: "pdf" | "docx" | "pptx" | "xlsx" | "md" | "json" | "csv" | "tsv" | "yaml" | "png" | "jpg";
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
  version: number | null; // null for live records of an integration
  page: string;
  heading: string | null;
  text: string;
  // Live records read from an integration (#): ticket, device, alert, indicator.
  kind?: "document" | "integration";
  integration?: string;
  product?: string;
  record?: string;
  record_kind?: string;
  url?: string | null;
  links?: Record<string, string>;
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
  check?: AnswerCheck | null;
}

/** Answer check: level 1 (values in the sources) and level 2 (a model checks each statement). */
export interface CheckIssue {
  level: (1 | 2)[];
  kind: "value" | "statement" | "uncited" | "no_citations";
  text: string;
  expected?: string;
  reason?: string;
}

export interface AnswerCheck {
  level2: "pending" | "ok" | "unavailable" | "off";
  issues: CheckIssue[];
  checker: { name: string; model: string } | null;
  hidden?: boolean;
  rewritten?: boolean;
}

export interface ChatSummary {
  id: string;
  title: string;
  scope_tenant_id: string | null;
  scope_name: string;
  updated_at: string;
  use_general?: boolean; // General Knowledge Base searched with the customer
  integration_ids?: string[]; // integrations chosen with #
}

export interface ChatFull extends ChatSummary {
  scope_available: boolean;
  shared?: boolean; // an active share link exists
  messages: ChatMessage[];
}

export interface ShareState {
  url: string | null; // only right after creating it: the link is not stored
  active: boolean;
  expires_at: string | null;
}

export interface SharedChat {
  title: string;
  scope_name: string;
  owner_name: string;
  messages: ChatMessage[];
  hidden: number; // exchanges left out: they used a customer you do not see
}

export interface Exchange {
  chat: ChatSummary;
  question: ChatMessage;
  answer: ChatMessage;
}

export interface ScopeOption {
  id: string | null;
  name: string;
  is_general?: boolean; // the General Knowledge Base alone
}

export interface IntegrationOption {
  id: string;
  name: string;
  product: string;
  type: "ticketing" | "edr" | "siem" | "identity";
}

// --- Integrations (admin) -------------------------------------------------------

export interface SchemaProp {
  type?: "string" | "boolean" | "integer";
  title?: string;
  description?: string;
  format?: string;
  enum?: string[];
  enumLabels?: string[];
  default?: string | boolean | number;
  secret?: boolean;
  maxLength?: number;
  showIf?: Record<string, string>;
}

export interface IntegrationPlugin {
  name: string;
  label: string;
  type: "ticketing" | "edr" | "siem" | "identity";
  vendor: string;
  version: string;
  description: string;
  operations: { name: string; label: string; description: string; returns: string; params: Record<string, string> }[];
  enabled: boolean;
  instances?: number | null;
  config_schema?: { properties: Record<string, SchemaProp>; required: string[] } | null;
}

export interface Integration {
  id: string;
  plugin: string;
  product: string;
  type: string | null;
  name: string;
  config: Record<string, string | boolean | number>;
  secrets_set: Record<string, boolean>;
  enabled: boolean;
  available: boolean;
  updated_at: string;
}

export interface LookupRecord {
  kind: string;
  id: string;
  title: string;
  url: string | null;
  fields: Record<string, string>;
  text: string | null;
  updated: string | null;
  links: Record<string, string>;
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
  role: "answers" | "checker"; // writes the answers, or checks them (one default per role)
  // Tenant admins receive only id, name, model, is_default and role.
}

export interface LlmPreset {
  label: string;
  kind: LlmKind;
  base_url: string;
  model: string;
  options: LlmProvider["options"];
}
