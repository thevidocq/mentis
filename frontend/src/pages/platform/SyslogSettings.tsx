import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import { Modal } from "../../components/Modal";

interface Syslog {
  enabled: boolean;
  host: string;
  port: number;
  protocol: "udp" | "tcp" | "tls";
  verify_tls: boolean;
  app_name: string;
  sent?: number;
  dropped?: number;
  last_error?: string | null;
}

export function SyslogSettings({ onClose }: { onClose: () => void }) {
  const [cfg, setCfg] = useState<Syslog | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api<Syslog>("/platform/syslog").then(setCfg).catch((e) => setMsg({ ok: false, text: errorText(e) })); }, []);
  if (!cfg) return null;
  const set = <K extends keyof Syslog>(k: K, v: Syslog[K]) => setCfg({ ...cfg, [k]: v });

  async function save(): Promise<boolean> {
    if (!cfg) return false;
    setMsg(null);
    try {
      const { enabled, host, port, protocol, verify_tls, app_name } = cfg;
      setCfg({ ...cfg, ...(await api<Syslog>("/platform/syslog", { method: "PUT", body: { enabled, host, port: Number(port), protocol, verify_tls, app_name } })) });
      return true;
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
      return false;
    }
  }

  async function test() {
    setBusy(true);
    if (await save()) {
      const r = await api<{ ok: boolean; message?: string; error?: string }>("/platform/syslog/test", { method: "POST" });
      setMsg(r.ok ? { ok: true, text: r.message ?? "Sent." } : { ok: false, text: r.error ?? "Sending failed." });
    }
    setBusy(false);
  }

  return (
    <Modal title="Syslog forwarding" onClose={onClose}
      footer={<>
        <button className="btn" disabled={busy || !cfg.host} onClick={test}>Save and send test</button>
        <button className="btn btn-primary" disabled={busy} onClick={async () => { if (await save()) onClose(); }}>Save</button>
      </>}>
      <p className="muted" style={{ margin: 0 }}>Every log event is also sent to your SIEM as RFC 5424 syslog, with the details as JSON. Chat content is never included.</p>
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => set("enabled", e.target.checked)} />Forward log events</label>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <label className="field" style={{ flex: 3, minWidth: 180 }}>Collector host<input className="input" value={cfg.host} onChange={(e) => set("host", e.target.value)} placeholder="siem.example.com" /></label>
        <label className="field" style={{ flex: 1, minWidth: 80 }}>Port<input className="input" type="number" value={cfg.port} onChange={(e) => set("port", Number(e.target.value))} /></label>
      </div>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <label className="field" style={{ flex: 1 }}>Protocol
          <select className="input" value={cfg.protocol} onChange={(e) => {
            const p = e.target.value as Syslog["protocol"];
            setCfg({ ...cfg, protocol: p, port: cfg.port === 514 || cfg.port === 6514 ? (p === "tls" ? 6514 : 514) : cfg.port });
          }}>
            <option value="udp">UDP</option><option value="tcp">TCP</option><option value="tls">TCP + TLS</option>
          </select>
        </label>
        <label className="field" style={{ flex: 1 }}>App name<input className="input" value={cfg.app_name} onChange={(e) => set("app_name", e.target.value)} /></label>
      </div>
      {cfg.protocol === "tls" && (
        <label className="check"><input type="checkbox" checked={cfg.verify_tls} onChange={(e) => set("verify_tls", e.target.checked)} />Verify the collector's certificate</label>
      )}
      {cfg.enabled && cfg.sent !== undefined && (
        <span className="muted small">This API process: {cfg.sent} sent, {cfg.dropped} dropped{cfg.last_error ? ` · last error: ${cfg.last_error}` : ""}</span>
      )}
      {msg && <div className={msg.ok ? "notice" : "error"} role="status">{msg.text}</div>}
    </Modal>
  );
}
