import { FormEvent, useState } from "react";
import { errorText } from "../../api/client";
import type { Integration, IntegrationPlugin, LookupRecord } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { integrationsApi } from "./integrationsApi";

/** "Try a lookup": runs one read operation, to check credentials, permissions and field mapping. */
export function TryLookup({ tenantId, integration, plugin, onClose }: {
  tenantId: string; integration: Integration; plugin: IntegrationPlugin; onClose: () => void;
}) {
  const [op, setOp] = useState(plugin.operations[0]?.name ?? "");
  const operation = plugin.operations.find((o) => o.name === op);
  const [args, setArgs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string; records: LookupRecord[] } | null>(null);

  async function run(e: FormEvent) {
    e.preventDefault();
    if (busy || !operation) return;
    setBusy(true);
    setResult(null);
    try {
      setResult(await integrationsApi.run(tenantId, integration.id, op, args));
    } catch (err) {
      setResult({ ok: false, detail: errorText(err), records: [] });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Try a lookup · ${integration.name}`} onClose={onClose}
      footer={<button type="button" className="btn" onClick={onClose}>Close</button>}>
      <form className="stack" style={{ gap: 12 }} onSubmit={run}>
        <label className="field">Lookup
          <select className="input" value={op} onChange={(e) => { setOp(e.target.value); setArgs({}); setResult(null); }}>
            {plugin.operations.map((o) => <option key={o.name} value={o.name}>{o.label}</option>)}
          </select>
          {operation && <span className="muted small">{operation.description}</span>}
        </label>
        {operation && Object.entries(operation.params).map(([k, d]) => (
          <label key={k} className="field">{d}
            <input className="input" value={args[k] ?? ""} maxLength={253} onChange={(e) => setArgs((a) => ({ ...a, [k]: e.target.value }))} />
          </label>
        ))}
        <div><button className="btn btn-primary" disabled={busy}><Icon name="search" />Run</button></div>
      </form>
      {result && (
        <div className="stack" style={{ gap: 8, marginTop: 12 }}>
          <div className={result.ok ? "notice" : "error"} role="status">{result.detail}</div>
          {result.records.map((r) => (
            <div key={r.id} className="card">
              <div className="card-head row" style={{ gap: 8 }}>
                <h2 style={{ fontSize: 14 }}>{r.id}</h2><span className="muted small">{r.title}</span>
                <span className="spacer" />
                {r.url && <a className="record-link" href={r.url} target="_blank" rel="noopener noreferrer nofollow"><Icon name="external" size={13} />Open</a>}
              </div>
              <div className="card-body small">
                <dl className="record-fields">
                  {Object.entries(r.fields).map(([k, v]) => <div key={k}><dt className="muted">{k}</dt><dd>{v}</dd></div>)}
                </dl>
                {r.text && <pre className="record-text">{r.text}</pre>}
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
