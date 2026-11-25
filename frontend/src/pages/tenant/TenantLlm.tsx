import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import type { LlmProvider } from "../../api/types";
import { useCurrentTenant } from "../../auth/currentTenant";
import { PageHead } from "../../layouts/AdminShell";
import { UsageTable, usd, useUsage } from "../platform/Usage";

interface Choice { provider_id: string | null; fallback_id: string | null }

// The tenant's LLM and fallback. Used by the tenant admin page and by the super-admin Tenants list.
export function TenantLlmForm({ tenantId, onSaved }: { tenantId: string; onSaved?: () => void }) {
  const [providers, setProviders] = useState<LlmProvider[] | null>(null);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    api<LlmProvider[]>("/llm/providers").then(setProviders).catch((e) => setMsg({ ok: false, text: errorText(e) }));
    api<Choice>(`/tenants/${tenantId}/llm`).then(setChoice).catch((e) => setMsg({ ok: false, text: errorText(e) }));
  }, [tenantId]);

  if (!providers || !choice) return msg ? <div className="error">{msg.text}</div> : null;
  const def = providers.find((p) => p.is_default);

  async function save() {
    setMsg(null);
    try {
      setChoice(await api<Choice>(`/tenants/${tenantId}/llm`, { method: "PUT", body: choice }));
      setMsg({ ok: true, text: "Saved." });
      onSaved?.();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  if (providers.length === 0) {
    return <div className="notice">No AI provider is configured yet. A super-admin must add one in <strong>AI providers</strong>.</div>;
  }
  const label = (p: LlmProvider) => `${p.name} — ${p.model}`;
  return (
    <div className="stack">
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
        {current && <div className="card"><div className="card-body"><TenantLlmForm key={current.id} tenantId={current.id} /></div></div>}
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
      <span className="muted small">{data.totals.questions} questions · estimated cost {usd(data.totals.cost_usd)}</span>
      <UsageTable rows={data.rows} showCustomer={false} />
    </>
  );
}
