import { FormEvent, useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import type { Smtp } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { PageHead } from "../../layouts/AdminShell";

export function SmtpSettings() {
  const { user } = useAuth();
  const [cfg, setCfg] = useState<Smtp | null>(null);
  const [password, setPassword] = useState("");
  const [testTo, setTestTo] = useState(user?.email ?? "");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api<Smtp>("/platform/smtp").then(setCfg).catch((e) => setMsg({ ok: false, text: errorText(e) })); }, []);
  if (!cfg) return <><PageHead title="Email (SMTP)" narrow />{msg && <div className="page-body narrow"><div className="error" role="alert">{msg.text}</div></div>}</>;

  const set = <K extends keyof Smtp>(k: K, v: Smtp[K]) => setCfg({ ...cfg, [k]: v });

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!cfg) return;
    setBusy(true);
    setMsg(null);
    try {
      const body: Record<string, unknown> = {
        host: cfg.host, port: Number(cfg.port), security: cfg.security, username: cfg.username,
        from_address: cfg.from_address || null,
      };
      if (password) body.password = password;
      setCfg(await api<Smtp>("/platform/smtp", { method: "PUT", body }));
      setPassword("");
      setMsg({ ok: true, text: "Saved." });
    } catch (err) {
      setMsg({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{ ok: boolean; error?: string }>("/platform/smtp/test", { method: "POST", body: { to: testTo } });
      setMsg(r.ok ? { ok: true, text: `Test email sent to ${testTo}.` } : { ok: false, text: r.error ?? "Sending failed." });
    } catch (err) {
      setMsg({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHead title="Email (SMTP)" narrow>
        {cfg.configured ? <span className="pill ok">Configured</span> : <span className="pill warn">Not configured</span>}
      </PageHead>
      <div className="page-body narrow">
        <p className="muted" style={{ margin: 0 }}>Used to send invitations. Without it, invitation links are shown to the admin to share manually.</p>
        <form className="card" onSubmit={save}>
          <div className="card-head"><h2>Server</h2></div>
          <div className="card-body stack">
            <div className="row" style={{ alignItems: "flex-end" }}>
              <label className="field" style={{ flex: 3, minWidth: 220 }}>Host<input className="input" value={cfg.host} onChange={(e) => set("host", e.target.value)} placeholder="smtp.example.com" /></label>
              <label className="field" style={{ flex: 1, minWidth: 90 }}>Port<input className="input" type="number" value={cfg.port} onChange={(e) => set("port", Number(e.target.value))} /></label>
              <label className="field" style={{ flex: 1, minWidth: 130 }}>Security
                <select className="input" value={cfg.security} onChange={(e) => set("security", e.target.value as Smtp["security"])}>
                  <option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option><option value="none">None</option>
                </select>
              </label>
            </div>
            <div className="row" style={{ alignItems: "flex-end" }}>
              <label className="field" style={{ flex: 1, minWidth: 220 }}>Username<input className="input" value={cfg.username} onChange={(e) => set("username", e.target.value)} autoComplete="off" /></label>
              <label className="field" style={{ flex: 1, minWidth: 220 }}>Password
                <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password"
                  placeholder={cfg.password_set ? "Stored — leave empty to keep" : ""} />
              </label>
            </div>
            <label className="field">Sender address<input className="input" type="email" value={cfg.from_address} onChange={(e) => set("from_address", e.target.value)} placeholder="mentis@example.com" /></label>
            <div><button className="btn btn-primary" disabled={busy}>Save</button></div>
          </div>
        </form>
        <div className="card">
          <div className="card-head"><h2>Send a test email</h2></div>
          <div className="card-body row" style={{ alignItems: "flex-end" }}>
            <label className="field" style={{ flex: 1, minWidth: 220 }}>Recipient<input className="input" type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} /></label>
            <button className="btn" onClick={test} disabled={busy || !cfg.configured}>Send test</button>
          </div>
        </div>
        {msg && <div className={msg.ok ? "notice" : "error"} role="status">{msg.text}</div>}
      </div>
    </>
  );
}
