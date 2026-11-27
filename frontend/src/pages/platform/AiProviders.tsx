import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import type { LlmKind, LlmPreset, LlmProvider } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { PageHead } from "../../layouts/AdminShell";
import { ModelPicker } from "./ModelPicker";

interface Form {
  id?: string;
  name: string;
  kind: LlmKind;
  base_url: string;
  model: string;
  api_key: string;
  api_key_set: boolean;
  saved_url?: string; // address the stored key belongs to
  reasoning_effort: string;
  max_tokens: string;
  price_in: string;
  price_out: string;
  is_default: boolean;
  role: Role;
}

type Role = "answers" | "checker";

const EMPTY: Form = { name: "", kind: "anthropic", base_url: "", model: "", api_key: "", api_key_set: false, reasoning_effort: "", max_tokens: "", price_in: "", price_out: "", is_default: false, role: "answers" };

const SECTIONS: { role: Role; title: string; text: string; empty: string }[] = [
  { role: "answers", title: "Answers", text: "The default answers for every customer unless the tenant chooses another one; a tenant can also set a fallback used when its LLM fails.",
    empty: "No model yet: the chat cannot answer until you add one." },
  { role: "checker", title: "Answer check", text: "Reads every answer and flags what is not in the sources (level 2). Customers choose in their LLM page what happens then.",
    empty: "No checker: each answer is checked by the same model that wrote it (or by the customer's own LLM), which tends to confirm what it wrote. Add a different model here for an independent check." },
];

function toForm(p: LlmProvider): Form {
  return { id: p.id, name: p.name, kind: p.kind, base_url: p.base_url, saved_url: p.base_url, model: p.model, api_key: "", api_key_set: p.api_key_set,
    reasoning_effort: p.options.reasoning_effort ?? "", max_tokens: p.options.max_tokens ? String(p.options.max_tokens) : "",
    price_in: p.options.price_in != null ? String(p.options.price_in) : "", price_out: p.options.price_out != null ? String(p.options.price_out) : "", is_default: p.is_default, role: p.role ?? "answers" };
}

export function AiProviders() {
  const [items, setItems] = useState<LlmProvider[] | null>(null);
  const [kinds, setKinds] = useState<Record<LlmKind, string>>({} as Record<LlmKind, string>);
  const [presets, setPresets] = useState<LlmPreset[]>([]);
  const [form, setForm] = useState<Form | null>(null);
  const [deleting, setDeleting] = useState<LlmProvider | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [advanced, setAdvanced] = useState(false);

  const load = () => api<LlmProvider[]>("/llm/providers").then(setItems).catch((e) => setMsg({ ok: false, text: errorText(e) }));
  useEffect(() => {
    load();
    api<{ kinds: Record<LlmKind, string>; presets: LlmPreset[] }>("/llm/kinds").then((r) => { setKinds(r.kinds); setPresets(r.presets); }).catch(() => undefined);
  }, []);

  async function save() {
    if (!form || saving) return;
    setFormError(null);
    const options: Record<string, unknown> = {};
    if (form.reasoning_effort) options.reasoning_effort = form.reasoning_effort;
    if (form.max_tokens) options.max_tokens = Number(form.max_tokens);
    if (form.price_in !== "") options.price_in = Number(form.price_in);
    if (form.price_out !== "") options.price_out = Number(form.price_out);
    const body: Record<string, unknown> = { name: form.name.trim(), kind: form.kind, base_url: form.base_url.trim(), model: form.model.trim(), options,
      is_default: form.is_default || firstOfRole(form.role, form.id), role: form.role };
    if (form.api_key) body.api_key = form.api_key;
    setSaving(true); // a double click must not add the provider twice
    try {
      await api(form.id ? `/llm/providers/${form.id}` : "/llm/providers", { method: form.id ? "PUT" : "POST", body });
      setForm(null);
      setMsg({ ok: true, text: "Saved." });
      load();
    } catch (e) {
      setFormError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  async function test(p: LlmProvider) {
    setBusy(p.id);
    setMsg(null);
    try {
      const r = await api<{ ok: boolean; reply?: string; error?: string }>(`/llm/providers/${p.id}/test`, { method: "POST" });
      const ok = p.role === "checker" ? `${p.name}: ${r.reply}.` : `${p.name} answered: “${r.reply}”.`;
      setMsg(r.ok ? { ok: true, text: ok } : { ok: false, text: `${p.name}: ${r.error ?? "the test failed"}.` });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function makeDefault(p: LlmProvider) {
    try {
      await api(`/llm/providers/${p.id}/default`, { method: "POST" });
      setMsg({ ok: true, text: `${p.name} is now the default ${p.role === "checker" ? "checker" : "model for answers"}.` });
      load();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  async function remove() {
    if (!deleting) return;
    try {
      await api(`/llm/providers/${deleting.id}`, { method: "DELETE" });
      setDeleting(null);
      load();
    } catch (e) {
      setDeleting(null);
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  const set = <K extends keyof Form>(k: K, v: Form[K]) => form && setForm({ ...form, [k]: v });
  // The first model of a role is its default; adding another never changes the default by itself.
  const firstOfRole = (role: Role, id?: string) => !(items ?? []).some((i) => (i.role ?? "answers") === role && i.id !== id);
  const open = (f: Form) => { setForm(f); setFormError(null); setAdvanced(!!f.id); }; // new: a preset fills the address

  return (
    <>
      <PageHead title="AI providers">
        <span className="spacer" />
        <button className="btn btn-primary" onClick={() => open({ ...EMPTY })}><Icon name="plus" />Add provider</button>
      </PageHead>
      <div className="page-body">
        <p className="muted" style={{ margin: 0 }}>
          LLMs used by Mentis: some <strong>write the answers</strong>, one <strong>checks them</strong> against the sources.
          Documents never leave Mentis except as the passages sent with each question.
        </p>
        {msg && <div className={msg.ok ? "notice" : "error"} role="status">{msg.text}</div>}
        {items && SECTIONS.map((sec) => {
          const rows = items.filter((p) => (p.role ?? "answers") === sec.role);
          return (
            <section key={sec.role} className="provider-section">
              <div className="provider-section-head"><h2>{sec.title}</h2><span className="muted small">{sec.text}</span></div>
              {rows.length === 0 ? <div className={`notice${sec.role === "checker" ? " notice-warn" : " muted"}`} role={sec.role === "checker" ? "status" : undefined}>{sec.empty}</div> : (
                <div className="table-wrap">
                  <table className="provider-table">
                    <colgroup><col style={{ width: "20%" }} /><col style={{ width: "19%" }} /><col style={{ width: "16%" }} /><col style={{ width: "17%" }} /><col style={{ width: "8%" }} /><col /></colgroup>
                    <thead><tr><th>Name</th><th>Type</th><th>Model</th><th>URL</th><th>Key</th><th /></tr></thead>
                    <tbody>
                      {rows.map((p) => (
                        <tr key={p.id}>
                          <td><strong>{p.name}</strong> {p.is_default && <span className="pill accent">{sec.role === "checker" ? "Default checker" : "Default"}</span>}</td>
                          <td className="muted">{kinds[p.kind] ?? p.kind}</td>
                          <td className="mono">{p.model}</td>
                          <td className="mono small">{p.base_url}</td>
                          <td>{p.api_key_set ? <span className="pill ok">Stored</span> : <span className="pill">None</span>}</td>
                          <td>
                            <div className="actions">
                              {!p.is_default && <button className="btn btn-sm" onClick={() => makeDefault(p)}>Set as default</button>}
                              <button className="btn btn-sm" disabled={busy === p.id} onClick={() => test(p)}
                                title={sec.role === "checker" ? "Checks a sample answer with a planted error" : "Asks for a one-word reply"}>
                                <Icon name="zap" />{busy === p.id ? "Testing…" : "Test"}
                              </button>
                              <button className="icon-btn" aria-label={`Edit ${p.name}`} onClick={() => open(toForm(p))}><Icon name="pencil" /></button>
                              <button className="icon-btn danger" aria-label={`Delete ${p.name}`} onClick={() => setDeleting(p)}><Icon name="trash" /></button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          );
        })}
      </div>

      {form && (
        <Modal title={form.id ? `Edit ${form.name}` : "Add provider"} onClose={() => setForm(null)}
          footer={<>
            <button className="btn" onClick={() => setForm(null)}>Cancel</button>
            <button className="btn btn-primary" disabled={saving || !form.name.trim() || !form.base_url.trim() || !form.model.trim()} onClick={save}>Save</button>
          </>}>
          <div className="field">Use for
            <div className="role-choice" role="radiogroup" aria-label="Use for">
              {([["answers", "Answers", "Writes the answers in the chat."], ["checker", "Answer check", "Checks every answer against its sources."]] as [Role, string, string][]).map(([r, t, d]) => (
                <button key={r} type="button" role="radio" aria-checked={form.role === r} className={`role-card${form.role === r ? " on" : ""}`}
                  disabled={!!form.id && !!items?.find((i) => i.id === form.id)?.is_default && form.role !== r}
                  onClick={() => set("role", r)}>
                  <span className="role-radio" aria-hidden="true" /><span><strong>{t}</strong><span className="muted small">{d}</span></span>
                </button>
              ))}
            </div>
          </div>
          {!form.id && presets.length > 0 && (
            <label className="field">Start from
              <select className="input" defaultValue="" onChange={(e) => {
                const p = presets[Number(e.target.value)];
                if (p) setForm({ ...form, name: form.name || p.label.replace(/ \(.*\)$/, ""), kind: p.kind, base_url: p.base_url, model: p.model || "",
                  reasoning_effort: p.options.reasoning_effort ?? "", max_tokens: p.options.max_tokens ? String(p.options.max_tokens) : "" });
                setAdvanced(false);
              }}>
                <option value="" disabled>Choose a preset…</option>
                {presets.map((p, i) => <option key={p.label} value={i}>{p.label}</option>)}
              </select>
            </label>
          )}
          <label className="field">Name<input className="input" maxLength={80} value={form.name} onChange={(e) => set("name", e.target.value)} /></label>
          <label className="field">API key
            <input className="input" type="password" autoComplete="new-password" value={form.api_key} onChange={(e) => set("api_key", e.target.value)}
              placeholder={form.api_key_set ? "Stored — leave empty to keep" : "Not needed for local Ollama / vLLM"} />
            {form.api_key_set && form.saved_url && form.base_url.replace(/\/+$/, "") !== form.saved_url && !form.api_key && (
              <span className="error small">The URL changed: enter the API key again. A stored key is never sent to a new address.</span>
            )}
          </label>
          <ModelPicker kind={form.kind} baseUrl={form.base_url} apiKey={form.api_key} providerId={form.id} value={form.model} onChange={(v) => set("model", v)} />
          {form.role === "checker" && (
            <span className="muted small">A small, fast model is enough. Fact-checking models such as Bespoke-MiniCheck (on Ollama) are recognised by name and used sentence by sentence.</span>
          )}
          {firstOfRole(form.role, form.id)
            ? <span className="muted small"><Icon name="check" size={13} /> {form.role === "checker" ? "The first checker becomes the default checker." : "The first model becomes the default for answers."}</span>
            : <label className="check"><input type="checkbox" checked={form.is_default} disabled={!!form.id && !!items?.find((i) => i.id === form.id)?.is_default}
                onChange={(e) => set("is_default", e.target.checked)} />{form.role === "checker" ? "Use as the default checker" : "Use as the default for all customers"}
                <span className="muted small"> (replaces the current one)</span></label>}
          <button type="button" className="advanced-toggle" aria-expanded={advanced || !form.base_url.trim()} onClick={() => setAdvanced(!advanced)}>
            <Icon name={advanced || !form.base_url.trim() ? "chevronDown" : "chevronRight"} size={14} />Advanced: API type, address, tokens and prices
          </button>
          {(advanced || !form.base_url.trim()) && <>
          <label className="field">API type
            <select className="input" value={form.kind} onChange={(e) => set("kind", e.target.value as LlmKind)}>
              {Object.entries(kinds).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </label>
          <label className="field">Base URL<input className="input mono" value={form.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder="https://api.anthropic.com" /></label>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <label className="field" style={{ flex: 1 }}>Reasoning effort
              <select className="input" value={form.reasoning_effort} onChange={(e) => set("reasoning_effort", e.target.value)}>
                <option value="">Model default</option><option value="minimal">Minimal</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
              </select>
            </label>
            <label className="field" style={{ flex: 1 }}>Max answer tokens<input className="input" type="number" min={100} max={16000} value={form.max_tokens} placeholder="4000" onChange={(e) => set("max_tokens", e.target.value)} /></label>
          </div>
          <span className="muted small">Reasoning effort applies to the OpenAI Responses API.</span>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <label className="field" style={{ flex: 1 }}>Price input (USD / 1M tokens)<input className="input" type="number" min={0} step="0.01" value={form.price_in} placeholder="optional" onChange={(e) => set("price_in", e.target.value)} /></label>
            <label className="field" style={{ flex: 1 }}>Price output (USD / 1M tokens)<input className="input" type="number" min={0} step="0.01" value={form.price_out} placeholder="optional" onChange={(e) => set("price_out", e.target.value)} /></label>
          </div>
          <span className="muted small">Prices only feed the cost estimate in LLM usage. Leave empty for internal models.</span>
          </>}
          {formError && <div className="error">{formError}</div>}
        </Modal>
      )}
      {deleting && (
        <Modal title="Delete provider" danger onClose={() => setDeleting(null)}
          footer={<><button className="btn" onClick={() => setDeleting(null)}>Cancel</button><button className="btn btn-danger" onClick={remove}>Delete</button></>}>
          <p style={{ margin: 0 }}>Delete <strong>{deleting.name}</strong>? Tenants using it must choose another model first.</p>
        </Modal>
      )}
    </>
  );
}
