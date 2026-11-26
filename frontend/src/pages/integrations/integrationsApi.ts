import { api } from "../../api/client";
import type { Integration, IntegrationPlugin, LookupRecord } from "../../api/types";

export interface TenantIntegrations { plugins: IntegrationPlugin[]; integrations: Integration[]; general: boolean }
export type ConfigValues = Record<string, string | boolean | number>;

export const integrationsApi = {
  // Super-admin: installed plugins and which are enabled.
  plugins: () => api<IntegrationPlugin[]>("/platform/integrations"),
  setEnabled: (names: string[]) => api<IntegrationPlugin[]>("/platform/integrations", { method: "PUT", body: { enabled: names } }),
  // Tenant admin: the customer's integrations.
  list: (tenantId: string) => api<TenantIntegrations>(`/tenants/${tenantId}/integrations`),
  create: (tenantId: string, plugin: string, name: string, config: ConfigValues) =>
    api<Integration>(`/tenants/${tenantId}/integrations`, { method: "POST", body: { plugin, name, config } }),
  update: (tenantId: string, id: string, body: { name?: string; config?: ConfigValues; enabled?: boolean }) =>
    api<Integration>(`/tenants/${tenantId}/integrations/${id}`, { method: "PUT", body }),
  remove: (tenantId: string, id: string) => api<void>(`/tenants/${tenantId}/integrations/${id}`, { method: "DELETE" }),
  test: (tenantId: string, id: string) => api<{ ok: boolean; detail: string }>(`/tenants/${tenantId}/integrations/${id}/test`, { method: "POST" }),
  run: (tenantId: string, id: string, operation: string, args: Record<string, string>) =>
    api<{ ok: boolean; detail: string; records: LookupRecord[] }>(`/tenants/${tenantId}/integrations/${id}/run`,
      { method: "POST", body: { operation, args } }),
};

export const TYPE_LABEL: Record<string, string> = { ticketing: "Ticketing", edr: "EDR", siem: "SIEM", identity: "Identity" };
