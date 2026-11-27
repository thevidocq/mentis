import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import type { LlmProvider } from "../../api/types";
import { useCurrentTenant } from "../../auth/currentTenant";
import { PageHead } from "../../layouts/AdminShell";
import { useAuth } from "../../auth/AuthContext";
import { UsageTable, useUsage } from "../platform/Usage";

type CheckMode = "warn" | "hide" | "off";
interface Choice {
  provider_id: string | null; fallback_id: string | null; checker_id: string | null; answer_check: CheckMode;
  editable?: boolean; admin_can_set_llm?: boolean;
  check_max_tokens?: number | null; check_max_tokens_default?: number;
}

const MODES: [CheckMode, string, string][] = [
  ["warn", "Show a warning", "The analyst sees the answer with what may not match the sources underlined and marked ⚠."],
  ["hide", "Hide the answer", "An answer that does not match the sources is written again once, then replaced by \"Not found\"."],
  ["off", "Don't check with a model", "Only level 1 runs: contacts, times and codes are still compared with the sources."],
];

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
  const answering = providers.filter((p) => (p.role ?? "answers") === "answers");
  const checkers = providers.filter((p) => p.role === "checker");
  const def = answering.find((p) => p.is_default);
  const defChecker = checkers.find((p) => p.is_default);

  async function save() {
    setMsg(null);
    try {
      if (!choice) return;
      setChoice(await api<Choice>(`/tenants/${tenantId}/llm`, { method: "PUT", body: {
        provider_id: choice.provider_id, fallback_id: choice.fallback_id, checker_id: choice.checker_id, answer_check: choice.answer_check,
        check_max_tokens: choice.check_max_tokens ?? null } }));
      setMsg({ ok: true, text: "Saved." });
      onSaved?.();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  const checkChoice = (
    <div className="stack" style={{ gap: 8 }}>
      <strong>Answer check</strong>
      <span className="muted small">Every answer is checked against its sources. When an answer does not match them:</span>
      <div className="mode-options" role="radiogroup" aria-label="Answer check">
        {MODES.map(([m, title, text]) => (
          <button key={m} type="button" role="radio" aria-checked={choice.answer_check === m} className={`role-card${choice.answer_check === m ? " on" : ""}`}
            onClick={() => setChoice({ ...choice, answer_check: m })}>
            <span className="role-radio" aria-hidden="true" />
            <span><strong>{title}{m === "warn" && <span className="pill accent" style={{ marginLeft: 8 }}>recommended</span>}</strong><span className="muted small">{text}</span></span>
          </button>
        ))}
      </div>
      {choice.answer_check !== "off" && (
        <label className="field" style={{ maxWidth: 300 }}>Max check tokens
          <input className="input" type="number" min={500} max={16000} value={choice.check_max_tokens ?? ""}
            placeholder={`${choice.check_max_tokens_default ?? 2500} (default)`}
            onChange={(e) => setChoice({ ...choice, check_max_tokens: e.target.value === "" ? null : Number(e.target.value) })} />
          <span className="muted small">
            How long the checker's reply may be, per group of 10 statements (500–16000). Raise it if answers show "Check not available"
            and the logs say the check was cut or empty; reasoning models (gpt-oss) need more, about 6000.
          </span>
        </label>
      )}
    </div>
  );

  if (answering.length === 0) {
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
        <div><span className="muted small">Model that checks the answers</span><br /><strong>{name(choice.checker_id)
          ?? (choice.provider_id ? `The LLM for answers (${name(choice.provider_id)})`
            : defChecker ? `Platform default (${label(defChecker)})`
            : `None set: the model that writes the answer checks it${def ? ` (${label(def)})` : ""}`)}</strong></div>
        {checkChoice}
        <div className="row">
          <button className="btn btn-primary" onClick={save}>Save</button>
          {msg && <span className={msg.ok ? "muted" : "error"} role="status">{msg.text}</span>}
        </div>
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
          {answering.map((p) => <option key={p.id} value={p.id}>{label(p)}</option>)}
        </select>
      </label>
      <label className="field">Fallback when it fails
        <select className="input" value={choice.fallback_id ?? ""} onChange={(e) => setChoice({ ...choice, fallback_id: e.target.value || null })}>
          <option value="">None</option>
          {answering.map((p) => <option key={p.id} value={p.id}>{label(p)}</option>)}
        </select>
      </label>
      <label className="field">Model that checks the answers
        <select className="input" value={choice.checker_id ?? ""} onChange={(e) => setChoice({ ...choice, checker_id: e.target.value || null })}>
          <option value="">{choice.provider_id ? "The LLM for answers chosen above" : defChecker ? `Platform default (${label(defChecker)})` : "Platform default (the model that writes the answer)"}</option>
          {checkers.map((p) => <option key={p.id} value={p.id}>{label(p)}</option>)}
        </select>
      </label>
      <span className="muted small">
        Use an internal model (gpt-oss, Ollama) when this customer's documents must not reach a cloud provider; in that case leave the fallback empty or internal too.
        With its own LLM, the answers of this customer are also checked by that LLM unless you choose a checker.
      </span>
      {checkChoice}
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
      <PageHead title="LLM" narrow />
      <div className="page-body narrow">
        <p className="muted" style={{ margin: 0 }}>Which AI model writes the answers about this customer. Analysts see the model's name under each answer.</p>
        {current?.is_general && <div className="notice">The General Knowledge Base is shared by all customers. With a customer, answers use that customer's LLM; questions on the General Knowledge Base alone use the platform default.</div>}
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
