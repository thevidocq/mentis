import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { PageHead } from "../../layouts/AdminShell";

interface Retention {
  chats_days: number;
  logs_days: number;
  last_purge: string | null;
  last_result: { chats: number; messages: number; log_events: number } | null;
}

const PRESETS = [30, 90, 180, 365, 730, 0];
const label = (d: number) => (d === 0 ? "Keep forever" : d % 365 === 0 ? `${d / 365} year${d > 365 ? "s" : ""}` : `${d} days`);

function DaysField({ title, help, value, onChange }: { title: string; help: string; value: number; onChange: (v: number) => void }) {
  const custom = !PRESETS.includes(value);
  return (
    <div className="stack" style={{ gap: 6 }}>
      <strong>{title}</strong>
      <span className="muted small">{help}</span>
      <div className="row">
        <select className="input" aria-label={title} value={custom ? "custom" : value} onChange={(e) => onChange(e.target.value === "custom" ? 60 : Number(e.target.value))}>
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
  if (!cfg) return <PageHead title="Retention" narrow />;

  async function save() {
    if (!cfg) return;
    try {
      setCfg(await api<Retention>("/platform/retention", { method: "PUT", body: { chats_days: cfg.chats_days, logs_days: cfg.logs_days } }));
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
      setMsg({ ok: true, text: `Deleted ${r?.chats ?? 0} chats (${r?.messages ?? 0} messages) and ${r?.log_events ?? 0} log events.` });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  return (
    <>
      <PageHead title="Retention" narrow />
      <div className="page-body narrow">
        <p className="muted" style={{ margin: 0 }}>How long Mentis keeps chats and log events. Older data is deleted once a day by the worker. Documents are not affected: they stay until an admin deletes them.</p>
        <div className="card">
          <div className="card-body stack">
            <DaysField title="Chats" help="A chat is deleted when it has had no new message for this long." value={cfg.chats_days} onChange={(v) => setCfg({ ...cfg, chats_days: v })} />
            <DaysField title="Log events" help="Audit and system events, including LLM usage figures." value={cfg.logs_days} onChange={(v) => setCfg({ ...cfg, logs_days: v })} />
            <div className="row"><button className="btn btn-primary" onClick={save}>Save</button></div>
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Purge</h2><span className="spacer" /><button className="btn btn-sm" onClick={() => setConfirm(true)}><Icon name="trash" />Purge now</button></div>
          <div className="card-body muted">
            {cfg.last_purge
              ? <>Last purge {new Date(cfg.last_purge).toLocaleString()}: {cfg.last_result?.chats ?? 0} chats, {cfg.last_result?.messages ?? 0} messages, {cfg.last_result?.log_events ?? 0} log events deleted.</>
              : "No purge has run yet."}
          </div>
        </div>
        {msg && <div className={msg.ok ? "notice" : "error"} role="status">{msg.text}</div>}
      </div>
      {confirm && (
        <Modal title="Purge now" danger onClose={() => setConfirm(false)}
          footer={<><button className="btn" onClick={() => setConfirm(false)}>Cancel</button><button className="btn btn-danger" onClick={purge}>Delete old data</button></>}>
          <p style={{ margin: 0 }}>Delete chats older than <strong>{label(cfg.chats_days)}</strong> and log events older than <strong>{label(cfg.logs_days)}</strong> now, using the saved settings? This cannot be undone.</p>
        </Modal>
      )}
    </>
  );
}
