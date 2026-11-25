import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import type { LlmKind, LlmPreset, LlmProvider } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { PageHead } from "../../layouts/AdminShell";

interface Form {
  id?: string;
  name: string;
  kind: LlmKind;
  base_url: string;
  model: string;
  api_key: string;
  api_key_set: boolean;
  reasoning_effort: string;
  max_tokens: string;
  is_default: boolean;
}

const EMPTY: Form = { name: "", kind: "anthropic", base_url: "", model: "", api_key: "", api_key_set: false, reasoning_effort: "", max_tokens: "", is_default: false };

function toForm(p: LlmProvider): Form {
  return { id: p.id, name: p.name, kind: p.kind, base_url: p.base_url, model: p.model, api_key: "", api_key_set: p.api_key_set,
    reasoning_effort: p.options.reasoning_effort ?? "", max_tokens: p.options.max_tokens ? String(p.options.max_tokens) : "", is_default: p.is_default };
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

  const load = () => api<LlmProvider[]>("/llm/providers").then(setItems).catch((e) => setMsg({ ok: false, text: errorText(e) }));
  useEffect(() => {
    load();
    api<{ kinds: Record<LlmKind, string>; presets: LlmPreset[] }>("/llm/kinds").then((r) => { setKinds(r.kinds); setPresets(r.presets); }).catch(() => undefined);
  }, []);

  async function save() {
    if (!form) return;
    setFormError(null);
    const options: Record<string, unknown> = {};
    if (form.reasoning_effort) options.reasoning_effort = form.reasoning_effort;
    if (form.max_tokens) options.max_tokens = Number(form.max_tokens);
    const body: Record<string, unknown> = { name: form.name.trim(), kind: form.kind, base_url: form.base_url.trim(), model: form.model.trim(), options, is_default: form.is_default };
    if (form.api_key) body.api_key = form.api_key;
    try {
      await api(form.id ? `/llm/providers/${form.id}` : "/llm/providers", { method: form.id ? "PUT" : "POST", body });
      setForm(null);
      setMsg({ ok: true, text: "Saved." });
      load();
    } catch (e) {
      setFormError(errorText(e));
    }
  }

  async function test(p: LlmProvider) {
    setBusy(p.id);
    setMsg(null);
    try {
      const r = await api<{ ok: boolean; reply?: string; error?: string }>(`/llm/providers/${p.id}/test`, { method: "POST" });
      setMsg(r.ok ? { ok: true, text: `${p.name} answered: “${r.reply}”.` } : { ok: false, text: r.error ?? "The test failed." });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function makeDefault(p: LlmProvider) {
    try {
      await api(`/llm/providers/${p.id}`, { method: "PUT", body: { name: p.name, kind: p.kind, base_url: p.base_url, model: p.model, options: p.options, is_default: true } });
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

  return (
    <>
      <PageHead title="AI providers">
        <span className="spacer" />
        <button className="btn btn-primary" onClick={() => { setForm({ ...EMPTY }); setFormError(null); }}><Icon name="plus" />Add provider</button>
      </PageHead>
      <div className="page-body">
        <p className="muted" style={{ margin: 0 }}>
          LLMs that write the answers. The <strong>default</strong> answers for every customer unless the tenant chooses another one;
          a tenant can also set a fallback used when its LLM fails. Documents never leave Mentis except as the passages sent with each question.
        </p>
        {msg && <div className={msg.ok ? "notice" : "error"} role="status">{msg.text}</div>}
        {items && items.length === 0 && (
          <div className="notice"><strong>No provider yet.</strong> The chat cannot answer until you add one. Start from a preset, e.g. Claude Haiku.</div>
        )}
        {items && items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Type</th><th>Model</th><th>URL</th><th>Key</th><th /></tr></thead>
              <tbody>
                {items.map((p) => (
                  <tr key={p.id}>
                    <td><strong>{p.name}</strong> {p.is_default && <span className="pill accent">Default</span>}</td>
                    <td className="muted">{kinds[p.kind] ?? p.kind}</td>
                    <td className="mono">{p.model}</td>
                    <td className="mono small">{p.base_url}</td>
                    <td>{p.api_key_set ? <span className="pill ok">Stored</span> : <span className="pill">None</span>}</td>
                    <td>
                      <div className="actions">
                        <button className="btn btn-sm" disabled={busy === p.id} onClick={() => test(p)}><Icon name="zap" />{busy === p.id ? "Testing…" : "Test"}</button>
                        {!p.is_default && <button className="icon-btn" aria-label={`Make ${p.name} default`} title="Make default" onClick={() => makeDefault(p)}><Icon name="star" /></button>}
                        <button className="icon-btn" aria-label={`Edit ${p.name}`} onClick={() => { setForm(toForm(p)); setFormError(null); }}><Icon name="pencil" /></button>
                        <button className="icon-btn danger" aria-label={`Delete ${p.name}`} onClick={() => setDeleting(p)}><Icon name="trash" /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {form && (
        <Modal title={form.id ? `Edit ${form.name}` : "Add provider"} onClose={() => setForm(null)}
          footer={<>
            <button className="btn" onClick={() => setForm(null)}>Cancel</button>
            <button className="btn btn-primary" disabled={!form.name.trim() || !form.base_url.trim() || !form.model.trim()} onClick={save}>Save</button>
          </>}>
          {!form.id && presets.length > 0 && (
            <label className="field">Start from
              <select className="input" defaultValue="" onChange={(e) => {
                const p = presets[Number(e.target.value)];
                if (p) setForm({ ...form, name: form.name || p.label.replace(/ \(.*\)$/, ""), kind: p.kind, base_url: p.base_url, model: p.model,
                  reasoning_effort: p.options.reasoning_effort ?? "", max_tokens: p.options.max_tokens ? String(p.options.max_tokens) : "" });
              }}>
                <option value="" disabled>Choose a preset…</option>
                {presets.map((p, i) => <option key={p.label} value={i}>{p.label}</option>)}
              </select>
            </label>
          )}
          <label className="field">Name<input className="input" maxLength={80} value={form.name} onChange={(e) => set("name", e.target.value)} /></label>
          <label className="field">API type
            <select className="input" value={form.kind} onChange={(e) => set("kind", e.target.value as LlmKind)}>
              {Object.entries(kinds).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </label>
          <label className="field">Base URL<input className="input mono" value={form.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder="https://api.anthropic.com" /></label>
          <label className="field">Model<input className="input mono" value={form.model} onChange={(e) => set("model", e.target.value)} /></label>
          <label className="field">API key
            <input className="input" type="password" autoComplete="new-password" value={form.api_key} onChange={(e) => set("api_key", e.target.value)}
              placeholder={form.api_key_set ? "Stored — leave empty to keep" : "Not needed for local Ollama / vLLM"} />
          </label>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <label className="field" style={{ flex: 1 }}>Reasoning effort
              <select className="input" value={form.reasoning_effort} onChange={(e) => set("reasoning_effort", e.target.value)}>
                <option value="">Model default</option><option value="minimal">Minimal</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
              </select>
            </label>
            <label className="field" style={{ flex: 1 }}>Max answer tokens<input className="input" type="number" min={100} max={16000} value={form.max_tokens} placeholder="1500" onChange={(e) => set("max_tokens", e.target.value)} /></label>
          </div>
          <span className="muted small">Reasoning effort applies to the Responses API (gpt-oss, Daybreak Blue).</span>
          <label className="check"><input type="checkbox" checked={form.is_default} disabled={!!form.id && !!items?.find((i) => i.id === form.id)?.is_default} onChange={(e) => set("is_default", e.target.checked)} />Default for all customers</label>
          {formError && <div className="error">{formError}</div>}
        </Modal>
      )}
      {deleting && (
        <Modal title="Delete provider" danger onClose={() => setDeleting(null)}
          footer={<><button className="btn" onClick={() => setDeleting(null)}>Cancel</button><button className="btn btn-danger" onClick={remove}>Delete</button></>}>
          <p style={{ margin: 0 }}>Delete <strong>{deleting.name}</strong>? Tenants using it must choose another LLM first.</p>
        </Modal>
      )}
    </>
  );
}
