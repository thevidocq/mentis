import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import type { Tenant, TenantSettings as Settings } from "../../api/types";
import { useCurrentTenant } from "../../auth/currentTenant";
import { PageHead } from "../../layouts/AdminShell";

const OPTIONS: { key: keyof Settings; label: string; help: string }[] = [
  { key: "include_general", label: "Include General documentation", help: "Answers also use the cross-customer knowledge base. Your own procedures win on conflict." },
  { key: "require_approval", label: "Approve new document versions before publishing", help: "A new version stays inactive until an admin approves it in the preview." },
  { key: "suggested_followups", label: "Suggested follow-up questions", help: "Show 2–3 clickable questions under each answer." },
];

export function TenantSettings() {
  const { current } = useCurrentTenant();
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (current) api<Tenant>(`/tenants/${current.id}`).then(setTenant).catch((e) => setError(errorText(e)));
  }, [current]);

  async function toggle(key: keyof Settings, value: boolean) {
    if (!tenant) return;
    const before = tenant;
    setTenant({ ...tenant, settings: { ...tenant.settings, [key]: value } }); // optimistic
    try {
      setTenant(await api<Tenant>(`/tenants/${tenant.id}`, { method: "PATCH", body: { settings: { [key]: value } } }));
    } catch (e) {
      setTenant(before);
      setError(errorText(e));
    }
  }

  return (
    <>
      <PageHead title="Settings" />
      <div className="page-body" style={{ maxWidth: 760 }}>
        {error && <div className="error">{error}</div>}
        {current?.is_general && <div className="notice">General is the shared documentation. These settings apply to customers, so there is nothing to set here.</div>}
        {tenant && !current?.is_general && (
          <div className="card">
            <div className="card-head"><h2>{tenant.name}</h2></div>
            <div className="card-body stack">
              {OPTIONS.map((o) => (
                <div key={o.key}>
                  <label className="check"><input type="checkbox" checked={tenant.settings[o.key]} onChange={(e) => toggle(o.key, e.target.checked)} /> {o.label}</label>
                  <div className="muted small" style={{ marginLeft: 28 }}>{o.help}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
