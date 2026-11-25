import { useRef, useState } from "react";
import { ApiError, errorText } from "../../api/client";
import { Icon } from "../../components/Icon";
import { PageHead } from "../../layouts/AdminShell";

async function importFile(file: File, apply: boolean): Promise<{ applied: boolean; changes: string[] }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/platform/config/import?apply=${apply}`, { method: "POST", credentials: "same-origin", headers: { "X-Mentis-Request": "1" }, body: form });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? `Import failed (${res.status}).`);
  return data;
}

export function Configuration() {
  const [file, setFile] = useState<File | null>(null);
  const [plan, setPlan] = useState<string[] | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function preview(f: File) {
    setFile(f);
    setPlan(null);
    setMsg(null);
    try {
      setPlan((await importFile(f, false)).changes);
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  async function apply() {
    if (!file) return;
    try {
      const r = await importFile(file, true);
      setMsg({ ok: true, text: `Imported: ${r.changes.length} change${r.changes.length === 1 ? "" : "s"} applied.` });
      setPlan(null);
      setFile(null);
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  return (
    <>
      <PageHead title="Backup and configuration" />
      <div className="page-body" style={{ maxWidth: 860 }}>
        <div className="card">
          <div className="card-head"><h2>Configuration</h2></div>
          <div className="card-body stack">
            <p className="muted" style={{ margin: 0 }}>
              A JSON file with platform settings (email, embedding, retention, syslog), AI providers and tenants with their settings and LLM.
              It never contains passwords, API keys, users, documents or chats. Use it to copy a setup from the lab to production or to keep it in version control.
            </p>
            <div className="row">
              <a className="btn" href="/api/platform/config/export" download><Icon name="download" />Export configuration</a>
              <button className="btn" onClick={() => input.current?.click()}><Icon name="upload" />Import…</button>
              <input ref={input} type="file" accept="application/json,.json" hidden aria-label="Configuration file"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) void preview(f); e.target.value = ""; }} />
            </div>
            {plan && (
              <div className="notice stack" style={{ gap: 8 }}>
                <strong>{file?.name}: {plan.length ? `${plan.length} change${plan.length === 1 ? "" : "s"}` : "nothing to change"}</strong>
                {plan.length > 0 && <ul style={{ margin: 0, paddingLeft: 20 }}>{plan.map((c) => <li key={c}>{c}</li>)}</ul>}
                <span className="muted small">Import only adds and updates: nothing is deleted. Enter the API keys of new AI providers afterwards.</span>
                <div className="row">
                  <button className="btn btn-primary btn-sm" disabled={!plan.length} onClick={apply}>Apply</button>
                  <button className="btn btn-sm" onClick={() => { setPlan(null); setFile(null); }}>Cancel</button>
                </div>
              </div>
            )}
            {msg && <div className={msg.ok ? "notice" : "error"} role="status">{msg.text}</div>}
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Backup and restore</h2></div>
          <div className="card-body stack">
            <p className="muted" style={{ margin: 0 }}>
              Full backups (database, documents, vector index and the <code>.env</code> secrets) are taken on the server with the scripts in the installation folder.
              Schedule the backup with cron and copy the folder off the server.
            </p>
            <pre className="code-block">{`cd mentis
./backup.sh                      # writes backups/mentis-<date>/
./restore.sh backups/mentis-<date>   # asks for confirmation`}</pre>
            <span className="muted small">See Help → Backup and configuration for the details.</span>
          </div>
        </div>
      </div>
    </>
  );
}
