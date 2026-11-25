import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import type { LlmProvider } from "../../api/types";
import { useCurrentTenant } from "../../auth/currentTenant";
import { PageHead } from "../../layouts/AdminShell";
import { useAuth } from "../../auth/AuthContext";
import { UsageTable, useUsage } from "../platform/Usage";

interface Choice { provider_id: string | null; fallback_id: string | null; editable?: boolean; admin_can_set_llm?: boolean }

// The tenant's LLM and fallback. Used by the tenant admin page and by the super-admin Tenants list.
export function TenantLlmForm({ tenantId, onSaved }: { tenantId: string; onSaved?: () => void }) {
  const [providers, setProviders] = useState<LlmProvider[] | null>(null);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const isSuper = useAuth().user?.role === "super_admin";

  useEffect(() => {
    api<LlmProvider[]>("/llm/providers").then(setProviders).catch((e) => setMsg({ ok: false, text: errorText(e) }));
    api<Choice>(`/tenants/${tenantId}/llm`).then(setChoice).catch((e) => setMsg({ ok: false, text: errorText(e) }));
  }, [tenantId]);

  if (!providers || !choice) return msg ? <div className="error">{msg.text}</div> : null;
  const def = providers.find((p) => p.is_default);

  async function save() {
    setMsg(null);
    try {
      if (!choice) return;
      setChoice(await api<Choice>(`/tenants/${tenantId}/llm`, { method: "PUT", body: { provider_id: choice.provider_id, fallback_id: choice.fallback_id } }));
      setMsg({ ok: true, text: "Saved." });
      onSaved?.();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  if (providers.length === 0) {
    return <div className="notice">No AI provider is configured yet. A super-admin must add one in <strong>AI providers</strong>.</div>;
  }
  async function setAdminCanSet(value: boolean) {
    setMsg(null);
    setChoice((c) => (c ? { ...c, admin_can_set_llm: value } : c)); // optimistic
    try {
      await api(`/tenants/${tenantId}`, { method: "PATCH", body: { settings: { admin_can_set_llm: value } } });
    } catch (e) {
      setChoice((c) => (c ? { ...c, admin_can_set_llm: !value } : c));
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  const label = (p: LlmProvider) => `${p.name} — ${p.model}`;
  const locked = choice.editable === false;
  if (locked) {
    const name = (id: string | null) => { const p = providers.find((x) => x.id === id); return p ? label(p) : null; };
    return (
      <div className="stack">
        <div className="notice">The super-admin chooses the LLM of this customer.</div>
        <div><span className="muted small">LLM for answers</span><br /><strong>{name(choice.provider_id) ?? `Platform default${def ? ` (${label(def)})` : ""}`}</strong></div>
        <div><span className="muted small">Fallback</span><br /><strong>{name(choice.fallback_id) ?? "None"}</strong></div>
      </div>
    );
  }
  return (
    <div className="stack">
      {isSuper && (
        <label className="check">
          <input type="checkbox" checked={choice.admin_can_set_llm ?? true} onChange={(e) => setAdminCanSet(e.target.checked)} />
          Tenant admins can choose the LLM of this customer
        </label>
      )}
      <label className="field">LLM for answers
        <select className="input" value={choice.provider_id ?? ""} onChange={(e) => setChoice({ ...choice, provider_id: e.target.value || null })}>
          <option value="">Platform default{def ? ` (${label(def)})` : ""}</option>
          {providers.map((p) => <option key={p.id} value={p.id}>{label(p)}</option>)}
        </select>
      </label>
      <label className="field">Fallback when it fails
        <select className="input" value={choice.fallback_id ?? ""} onChange={(e) => setChoice({ ...choice, fallback_id: e.target.value || null })}>
          <option value="">None</option>
          {providers.map((p) => <option key={p.id} value={p.id}>{label(p)}</option>)}
        </select>
      </label>
      <span className="muted small">
        Use an internal model (gpt-oss, Ollama) when this customer's documents must not reach a cloud provider; in that case leave the fallback empty or internal too.
      </span>
      <div className="row">
        <button className="btn btn-primary" onClick={save}>Save</button>
        {msg && <span className={msg.ok ? "muted" : "error"} role="status">{msg.text}</span>}
      </div>
    </div>
  );
}

export function TenantLlm() {
  const { current } = useCurrentTenant();
  return (
    <>
      <PageHead title="LLM" />
      <div className="page-body" style={{ maxWidth: 760 }}>
        <p className="muted" style={{ margin: 0 }}>Which AI model writes the answers about this customer. Analysts see the model's name under each answer.</p>
        {current?.is_general && <div className="notice">General is the shared documentation. With a customer, answers use that customer's LLM; questions on General alone use the platform default.</div>}
        {current && !current.is_general && <div className="card"><div className="card-body"><TenantLlmForm key={current.id} tenantId={current.id} /></div></div>}
        <TenantUsage />
      </div>
    </>
  );
}

function TenantUsage() {
  const { data } = useUsage(30);
  if (!data) return null;
  return (
    <>
      <h2>Usage, last 30 days</h2>
      <span className="muted small">{data.totals.questions} questions</span>
      <UsageTable rows={data.rows} showCustomer={false} showCost={false} />
    </>
  );
}
