import { FormEvent, useState } from "react";
import { errorText } from "../../api/client";
import type { Integration, IntegrationPlugin } from "../../api/types";
import { Modal } from "../../components/Modal";
import { ConfigForm, defaults, payload } from "./ConfigForm";
import { integrationsApi, TYPE_LABEL, type ConfigValues } from "./integrationsApi";

/** Add an integration (choose the type, then fill its form) or edit one. */
export function IntegrationDialog({ tenantId, plugins, editing, onClose, onSaved }: {
  tenantId: string;
  plugins: IntegrationPlugin[];
  editing: Integration | null;
  onClose: () => void;
  onSaved: (i: Integration) => void;
}) {
  const [pluginName, setPluginName] = useState(editing?.plugin ?? plugins[0]?.name ?? "");
  const plugin = plugins.find((p) => p.name === pluginName);
  const [name, setName] = useState(editing?.name ?? "");
  const [values, setValues] = useState<ConfigValues>(editing ? { ...editing.config } : plugin ? defaults(plugin) : {});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function choose(p: string) {
    setPluginName(p);
    const pl = plugins.find((x) => x.name === p);
    setValues(pl ? defaults(pl) : {});
    setSecrets({});
  }

  async function save(e?: FormEvent) {
    e?.preventDefault();
    if (!plugin || busy) return;
    setBusy(true);
    setError(null);
    try {
      const config = payload(plugin, values, secrets);
      const saved = editing
        ? await integrationsApi.update(tenantId, editing.id, { name: name.trim(), config })
        : await integrationsApi.create(tenantId, plugin.name, name.trim(), config);
      onSaved(saved);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={editing ? `Edit ${editing.name}` : "Add integration"} onClose={onClose}
      footer={<>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn btn-primary" disabled={busy || !plugin || !name.trim()} onClick={() => save()}>
          {editing ? "Save" : "Add"}
        </button>
      </>}>
      <form className="stack" style={{ gap: 12 }} onSubmit={save}>
        {!editing && (
          <label className="field">Type
            <select className="input" value={pluginName} onChange={(e) => choose(e.target.value)}>
              {plugins.map((p) => <option key={p.name} value={p.name}>{p.label} · {TYPE_LABEL[p.type] ?? p.type}</option>)}
            </select>
            {plugin && <span className="muted small">{plugin.description}</span>}
          </label>
        )}
        <label className="field">Name *
          <input className="input" value={name} maxLength={80} onChange={(e) => setName(e.target.value)}
            placeholder={plugin ? `${plugin.label} production` : ""} />
          <span className="muted small">Shown to analysts after # in the chat.</span>
        </label>
        {plugin ? (
          <ConfigForm plugin={plugin} values={values} secrets={secrets} stored={editing?.secrets_set}
            onChange={(k, v) => setValues((x) => ({ ...x, [k]: v }))} onSecret={(k, v) => setSecrets((x) => ({ ...x, [k]: v }))} />
        ) : (
          <div className="notice">This integration type is not enabled any more. Ask a super-admin.</div>
        )}
        <p className="muted small" style={{ margin: 0 }}>
          Read only: Mentis never changes anything in this system. Use an account with read permissions only.
          Credentials are stored encrypted and never shown again; they are sent only to the address above.
        </p>
        {error && <div className="error" role="alert">{error}</div>}
        <button type="submit" hidden />
      </form>
    </Modal>
  );
}
