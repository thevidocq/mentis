import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { PageHead } from "../../layouts/AdminShell";

interface Retention {
  chats_days: number;
  logs_days: number;
  versions_keep: number;
  last_purge: string | null;
  last_result: { chats: number; messages: number; log_events: number; versions?: number; orphan_files?: number; orphan_vectors?: number } | null;
}

const KEEP = [0, 1, 3, 5, 10];
const keepLabel = (n: number) => (n === 0 ? "Keep all versions" : `Keep the last ${n} older ${n === 1 ? "version" : "versions"}`);
const result = (r: Retention["last_result"]) => r
  ? `${r.chats} chats (${r.messages} messages), ${r.log_events} log events, ${r.versions ?? 0} old document versions deleted${(r.orphan_files ?? 0) + (r.orphan_vectors ?? 0) ? `; ${(r.orphan_files ?? 0) + (r.orphan_vectors ?? 0)} leftover files or index entries cleaned` : ""}`
  : "";

const PRESETS = [30, 90, 180, 365, 730, 0];
const label = (d: number) => (d === 0 ? "Keep forever" : d % 365 === 0 ? `${d / 365} year${d > 365 ? "s" : ""}` : `${d} days`);

function DaysField({ title, help, value, onChange }: { title: string; help: string; value: number; onChange: (v: number) => void }) {
  // Stays on Custom while typing: clearing the box (0) must not switch to "Keep forever" and hide it.
  const [customOn, setCustomOn] = useState(!PRESETS.includes(value));
  const custom = customOn || !PRESETS.includes(value);
  return (
    <div className="stack" style={{ gap: 6 }}>
      <strong>{title}</strong>
      <span className="muted small">{help}</span>
      <div className="row">
        <select className="input" aria-label={title} value={custom ? "custom" : value} onChange={(e) => { setCustomOn(e.target.value === "custom"); onChange(e.target.value === "custom" ? 60 : Number(e.target.value)); }}>
          {PRESETS.map((d) => <option key={d} value={d}>{label(d)}</option>)}
          <option value="custom">Custom…</option>
        </select>
        {custom && <label className="row small muted" style={{ gap: 6 }}><input className="input" type="number" min={1} max={3650} value={value} style={{ width: 100 }} onChange={(e) => onChange(Number(e.target.value))} />days</label>}
      </div>
    </div>
  );
}

export function RetentionSettings() {
  const [cfg, setCfg] = useState<Retention | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirm, setConfirm] = useState(false);

  useEffect(() => { api<Retention>("/platform/retention").then(setCfg).catch((e) => setMsg({ ok: false, text: errorText(e) })); }, []);
  if (!cfg) return <><PageHead title="Retention" narrow />{msg && <div className="page-body narrow"><div className="error" role="alert">{msg.text}</div></div>}</>;

  async function save() {
    if (!cfg) return;
    try {
      setCfg(await api<Retention>("/platform/retention", { method: "PUT", body: { chats_days: cfg.chats_days, logs_days: cfg.logs_days, versions_keep: cfg.versions_keep } }));
      setMsg({ ok: true, text: "Saved. The next daily purge applies it; use Purge now to apply it immediately." });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  async function purge() {
    setConfirm(false);
    try {
      const r = await api<Retention["last_result"]>("/platform/retention/purge", { method: "POST" });
      setCfg(await api<Retention>("/platform/retention"));
      setMsg({ ok: true, text: `Deleted ${result(r)}.` });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  return (
    <>
      <PageHead title="Retention" narrow />
      <div className="page-body narrow">
        <p className="muted" style={{ margin: 0 }}>How long Mentis keeps chats, log events and old document versions. Older data is deleted once a day by the worker. Documents in use are never affected: they stay until an admin deletes them.</p>
        <div className="card">
          <div className="card-body stack">
            <DaysField title="Chats" help="A chat is deleted when it has had no new message for this long." value={cfg.chats_days} onChange={(v) => setCfg({ ...cfg, chats_days: v })} />
            <DaysField title="Log events" help="Audit and system events, including LLM usage figures." value={cfg.logs_days} onChange={(v) => setCfg({ ...cfg, logs_days: v })} />
            <div className="stack" style={{ gap: 6 }}>
              <strong>Old document versions</strong>
              <span className="muted small">Per document, the version in use, the latest one and versions waiting approval are always kept. Older versions beyond this number are deleted with their files, page images and index entries.</span>
              <div className="row">
                <select className="input" aria-label="Old document versions" value={cfg.versions_keep ?? 0} onChange={(e) => setCfg({ ...cfg, versions_keep: Number(e.target.value) })}>
                  {KEEP.map((n) => <option key={n} value={n}>{keepLabel(n)}</option>)}
                </select>
              </div>
            </div>
            <div className="row"><button className="btn btn-primary" onClick={save}>Save</button></div>
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Purge</h2><span className="spacer" /><button className="btn btn-sm" onClick={() => setConfirm(true)}><Icon name="trash" />Purge now</button></div>
          <div className="card-body muted">
            {cfg.last_purge
              ? <>Last purge {new Date(cfg.last_purge).toLocaleString()}: {result(cfg.last_result)}.</>
              : "No purge has run yet."}
          </div>
        </div>
        {msg && <div className={msg.ok ? "notice" : "error"} role="status">{msg.text}</div>}
      </div>
      {confirm && (
        <Modal title="Purge now" danger onClose={() => setConfirm(false)}
          footer={<><button className="btn" onClick={() => setConfirm(false)}>Cancel</button><button className="btn btn-danger" onClick={purge}>Delete old data</button></>}>
          <p style={{ margin: 0 }}>Delete chats older than <strong>{label(cfg.chats_days)}</strong> and log events older than <strong>{label(cfg.logs_days)}</strong>{cfg.versions_keep ? <> and old document versions beyond the last <strong>{cfg.versions_keep}</strong></> : null} now, using the saved settings? This cannot be undone.</p>
        </Modal>
      )}
    </>
  );
}
