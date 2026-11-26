import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { api, errorText } from "../../api/client";
import type { Tenant } from "../../api/types";
import { Icon } from "../../components/Icon";
import { PageHead } from "../../layouts/AdminShell";
import { SyslogSettings } from "./SyslogSettings";

interface LogRow {
  id: string;
  ts: string;
  kind: "audit" | "system";
  level: "info" | "warning" | "error";
  action: string;
  actor_email: string | null;
  tenant: string | null;
  target: string | null;
  ip: string | null;
  detail: Record<string, unknown>;
}

const PAGE = 100;
const PERIODS: Record<string, number | null> = { "Last 24 hours": 1, "Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90, "All": null };
const LEVEL_PILL = { info: "", warning: "warn", error: "danger" } as const;

interface Filters { period: string; kind: string; level: string; tenant: string; action: string; q: string }
const EMPTY: Filters = { period: "Last 7 days", kind: "", level: "", tenant: "", action: "", q: "" };

function query(f: Filters, extra: Record<string, string | number> = {}) {
  const p = new URLSearchParams();
  const days = PERIODS[f.period];
  if (days) p.set("since", new Date(Date.now() - days * 86_400_000).toISOString());
  if (f.kind) p.set("kind", f.kind);
  if (f.level) p.set("level", f.level);
  if (f.tenant) p.set("tenant_id", f.tenant);
  if (f.action) p.set("action", f.action);
  if (f.q.trim()) p.set("q", f.q.trim());
  for (const [k, v] of Object.entries(extra)) p.set(k, String(v));
  return p.toString();
}

export function Logs() {
  const [f, setF] = useState<Filters>(EMPTY);
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<LogRow[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [actions, setActions] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [syslogOpen, setSyslogOpen] = useState(false);

  useEffect(() => {
    api<Tenant[]>("/tenants").then(setTenants).catch(() => undefined);
    api<string[]>("/logs/actions").then(setActions).catch(() => undefined);
  }, []);

  useEffect(() => { const t = setTimeout(() => setF((x) => ({ ...x, q })), 300); return () => clearTimeout(t); }, [q]);

  const seq = useRef(0); // typing in the search box: an older, slower answer must not replace a newer one
  const load = useCallback((off: number) => {
    const mine = ++seq.current;
    api<{ items: LogRow[]; total: number }>(`/logs?${query(f, { limit: PAGE, offset: off })}`)
      .then((r) => { if (mine === seq.current) { setRows(r.items); setTotal(r.total); setOffset(off); setError(null); } })
      .catch((e) => { if (mine === seq.current) setError(errorText(e)); });
  }, [f]);

  useEffect(() => { load(0); }, [load]);

  const set = (k: keyof Filters, v: string) => setF({ ...f, [k]: v });
  // Groups like "auth.", "chat." for the action filter.
  const prefixes = Array.from(new Set(actions.map((a) => a.split(".")[0] + "."))).sort();

  return (
    <>
      <PageHead title="Logs">
        <span className="muted">{total.toLocaleString()} events</span>
        <span className="spacer" />
        <button className="btn" onClick={() => setSyslogOpen(true)}><Icon name="link" />Syslog forwarding</button>
        <a className="btn" href={`/api/logs/export?${query(f)}`} download><Icon name="download" />Export CSV</a>
      </PageHead>
      <div className="page-body">
        <div className="row filters">
          <select className="input" aria-label="Period" value={f.period} onChange={(e) => set("period", e.target.value)}>
            {Object.keys(PERIODS).map((p) => <option key={p}>{p}</option>)}
          </select>
          <select className="input" aria-label="Type" value={f.kind} onChange={(e) => set("kind", e.target.value)}>
            <option value="">All types</option><option value="audit">Audit</option><option value="system">System</option>
          </select>
          <select className="input" aria-label="Level" value={f.level} onChange={(e) => set("level", e.target.value)}>
            <option value="">All levels</option><option value="info">Info</option><option value="warning">Warning</option><option value="error">Error</option>
          </select>
          <select className="input" aria-label="Tenant" value={f.tenant} onChange={(e) => set("tenant", e.target.value)}>
            <option value="">All tenants</option><option value="none">Platform (no tenant)</option>
            {tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <select className="input" aria-label="Action" value={f.action} onChange={(e) => set("action", e.target.value)}>
            <option value="">All actions</option>
            {prefixes.map((p) => <option key={p} value={p}>{p}*</option>)}
            {actions.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <input className="input" type="search" aria-label="Search logs" placeholder="User, target, action, IP…" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
          {(JSON.stringify({ ...f, q: "" }) !== JSON.stringify({ ...EMPTY, q: "" }) || q) && (
            <button className="btn btn-sm" onClick={() => { setF(EMPTY); setQ(""); }}><Icon name="x" />Clear</button>
          )}
        </div>
        {error && <div className="error" role="alert">{error}</div>}
        <div className="table-wrap">
          <table className="logs-table">
            <thead><tr><th>Time</th><th>Level</th><th>Type</th><th>Action</th><th>User</th><th>Tenant</th><th>Target</th><th>IP</th></tr></thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={8} className="muted">No events match these filters.</td></tr>}
              {rows.map((r) => (
                <Fragment key={r.id}>
                  <tr className="clickable" onClick={() => setOpen(open === r.id ? null : r.id)} aria-expanded={open === r.id}>
                    <td className="nowrap">{new Date(r.ts).toLocaleString()}</td>
                    <td><span className={`pill ${LEVEL_PILL[r.level]}`}>{r.level}</span></td>
                    <td className="muted">{r.kind}</td>
                    <td className="mono small nowrap">{r.action}</td>
                    <td>{r.actor_email ?? <span className="muted">system</span>}</td>
                    <td>{r.tenant ?? <span className="muted">—</span>}</td>
                    <td className="ellipsis" title={r.target ?? ""}>{r.target ?? "—"}</td>
                    <td className="muted small">{r.ip ?? "—"}</td>
                  </tr>
                  {open === r.id && (
                    <tr><td colSpan={8} className="log-detail"><pre>{JSON.stringify(r.detail, null, 2)}</pre></td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {total > PAGE && (
          <div className="row">
            <button className="btn btn-sm" disabled={offset === 0} onClick={() => load(Math.max(0, offset - PAGE))}>Newer</button>
            <span className="muted small">{offset + 1}–{Math.min(offset + PAGE, total)} of {total.toLocaleString()}</span>
            <button className="btn btn-sm" disabled={offset + PAGE >= total} onClick={() => load(offset + PAGE)}>Older</button>
          </div>
        )}
        <span className="muted small">Chat events carry metadata only (customer, model, tokens, time), never questions or answers. Events older than the log retention period are deleted.</span>
      </div>
      {syslogOpen && <SyslogSettings onClose={() => setSyslogOpen(false)} />}
    </>
  );
}
