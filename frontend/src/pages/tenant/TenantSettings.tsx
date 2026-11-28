import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import type { Tenant, TenantSettings as Settings } from "../../api/types";
import { useCurrentTenant } from "../../auth/currentTenant";
import { PageHead } from "../../layouts/AdminShell";
import { IntegrationModeForm } from "../integrations/IntegrationModeForm";

type Flag = "include_general" | "require_approval" | "approval_by_another" | "suggested_followups";

const OPTIONS: { key: Flag; label: string; help: string }[] = [
  { key: "include_general", label: "Include the General Knowledge Base", help: "Answers also use the general knowledge shared by all customers. Your own procedures win on conflict." },
  { key: "require_approval", label: "Approve new document versions before publishing", help: "A new version stays inactive until an admin approves it in the preview." },
  { key: "approval_by_another", label: "Approval by another person", help: "A version waiting for approval is approved by someone other than the person who uploaded it (they can still reject it)." },
  { key: "suggested_followups", label: "Suggested follow-up questions", help: "Show 2–3 clickable questions under each answer." },
];

export function TenantSettings() {
  const { current } = useCurrentTenant();
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (current) api<Tenant>(`/tenants/${current.id}`).then(setTenant).catch((e) => setError(errorText(e)));
  }, [current]);

  async function toggle(key: keyof Settings, value: boolean | number | string | null) {
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
      <PageHead title="Settings" narrow />
      <div className="page-body narrow">
        {error && <div className="error">{error}</div>}
        {current?.is_general && <div className="notice">The General Knowledge Base is shared by all customers: its documents always need approval, and the other settings apply to customers.</div>}
        {tenant && current?.is_general && (
          <div className="card">
            <div className="card-head"><h2>{tenant.name}</h2></div>
            <div className="card-body stack">
              <div>
                <label className="check"><input type="checkbox" checked={!!tenant.settings.approval_by_another} onChange={(e) => toggle("approval_by_another", e.target.checked)} /> Approval by another person</label>
                <div className="muted small" style={{ marginLeft: 28 }}>A new version is approved by someone other than the person who uploaded it (they can still reject it). Recommended when more than one person manages the General Knowledge Base: its documents reach every customer's answers.</div>
              </div>
            </div>
          </div>
        )}
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
              <PassagesField value={tenant.settings.chat_passages ?? null} fallback={tenant.chat_passages_default ?? 8}
                onSave={(v) => toggle("chat_passages", v)} />
              <div>
                <label className="field" style={{ maxWidth: 260 }}>Questions that ask several things
                  <select className="input" value={tenant.settings.passage_variety ?? "normal"} onChange={(e) => toggle("passage_variety", e.target.value)}>
                    <option value="normal">Normal (default)</option>
                    <option value="high">High</option>
                    <option value="off">Off</option>
                  </select>
                </label>
                <div className="muted small">
                  Mentis picks passages that are relevant <em>and</em> different from each other, so a question asking two things (a procedure and a contact, say) finds passages for both. <strong>High</strong> gives more room to the second topic; <strong>Off</strong> keeps only the passages closest to the whole question.
                </div>
              </div>
            </div>
          </div>
        )}
        {tenant && !current?.is_general && (
          <div className="card">
            <div className="card-head"><h2>Integrations</h2></div>
            <div className="card-body"><IntegrationModeForm tenantId={tenant.id} /></div>
          </div>
        )}
      </div>
    </>
  );
}

/** Passages read per answer: empty = platform default. Saved when the field loses focus. */
function PassagesField({ value, fallback, onSave }: { value: number | null; fallback: number; onSave: (v: number | null) => void }) {
  const [text, setText] = useState(value == null ? "" : String(value));
  useEffect(() => setText(value == null ? "" : String(value)), [value]);
  const n = text.trim() === "" ? null : Number(text);
  const invalid = n !== null && (!Number.isInteger(n) || n < 3 || n > 20);
  return (
    <div>
      <label className="field" style={{ maxWidth: 260 }}>Passages read per answer
        <input className="input" type="number" min={3} max={20} value={text} placeholder={`${fallback} (platform default)`}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => { if (!invalid && n !== value) onSave(n); }} />
      </label>
      <div className="muted small">
        How many document passages the AI reads to answer (3–20). More helps questions that ask several things at once or need long procedures; fewer keeps answers focused and cheaper. Empty: platform default ({fallback}).
      </div>
      {invalid && <div className="error small">Enter a number from 3 to 20, or leave it empty.</div>}
    </div>
  );
}
