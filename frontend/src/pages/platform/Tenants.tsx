import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import type { Tenant } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { TenantLlmForm } from "../tenant/TenantLlm";
import { PageHead } from "../../layouts/AdminShell";

const STATUSES: Tenant["status"][] = ["active", "onboarding", "disabled"];
const statusPill = (s: Tenant["status"]) => (s === "active" ? "ok" : s === "onboarding" ? "warn" : "danger");

export function Tenants() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Tenant | "new" | null>(null);
  const [deleting, setDeleting] = useState<Tenant | null>(null);
  const [llmFor, setLlmFor] = useState<Tenant | null>(null);

  const load = useCallback(() => {
    api<Tenant[]>("/tenants").then(setTenants).catch((e) => setError(errorText(e)));
  }, []);
  useEffect(load, [load]);

  const customers = tenants.filter((t) => !t.is_global).length;

  return (
    <>
      <PageHead title="Tenants">
        <span className="muted">{customers} {customers === 1 ? "customer" : "customers"} · 1 General</span>
        <button className="btn btn-primary spacer" onClick={() => setEditing("new")}><Icon name="plus" />Onboard tenant</button>
      </PageHead>
      <div className="page-body">
        {error && <div className="error">{error}</div>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Tenant</th><th>Type</th><th>Users</th><th>Status</th><th style={{ textAlign: "right" }}>Actions</th></tr>
            </thead>
            <tbody>
              {tenants.map((t) => (
                <tr key={t.id}>
                  <td><strong>{t.name}</strong><div className="muted small">{t.slug}</div></td>
                  <td>{t.is_global ? <span className="pill accent">Cross-customer</span> : "Customer"}</td>
                  <td>{t.users}</td>
                  <td><span className={`pill ${statusPill(t.status)}`}>{t.status}</span></td>
                  <td>
                    <div className="actions">
                      {!t.is_global && <button className="icon-btn" aria-label={`LLM of ${t.name}`} title="LLM" onClick={() => setLlmFor(t)}><Icon name="brain" /></button>}
                      <button className="icon-btn" aria-label={`Edit ${t.name}`} onClick={() => setEditing(t)}><Icon name="pencil" /></button>
                      {t.is_global ? (
                        <span className="icon-btn" style={{ border: 0, color: "var(--muted)" }} title="The General tenant cannot be deleted"><Icon name="lock" /></span>
                      ) : (
                        <button className="icon-btn danger" aria-label={`Delete ${t.name}`} onClick={() => setDeleting(t)}><Icon name="trash" /></button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {editing && <TenantForm tenant={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
      {llmFor && <Modal title={`LLM of ${llmFor.name}`} onClose={() => setLlmFor(null)}><TenantLlmForm tenantId={llmFor.id} /></Modal>}
      {deleting && <DeleteTenant tenant={deleting} onClose={() => setDeleting(null)} onDeleted={() => { setDeleting(null); load(); }} />}
    </>
  );
}

function TenantForm({ tenant, onClose, onSaved }: { tenant: Tenant | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(tenant?.name ?? "");
  const [status, setStatus] = useState<Tenant["status"]>(tenant?.status ?? "onboarding");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (tenant) {
        const body: Record<string, string> = {};
        if (name !== tenant.name) body.name = name;
        if (status !== tenant.status) body.status = status;
        await api(`/tenants/${tenant.id}`, { method: "PATCH", body });
      } else {
        await api("/tenants", { method: "POST", body: { name, status } });
      }
      onSaved();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={tenant ? `Edit ${tenant.name}` : "Onboard tenant"} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="tenant-form" disabled={busy || name.trim().length < 2}>Save</button></>}>
      <form id="tenant-form" className="stack" onSubmit={submit}>
        <label className="field">Customer name
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
        </label>
        {!tenant?.is_global && (
          <label className="field">Status
            <select className="input" value={status} onChange={(e) => setStatus(e.target.value as Tenant["status"])}>
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
        )}
        {!tenant && <span className="muted small">Then invite the customer's tenant admin from Users.</span>}
        {error && <div className="error" role="alert">{error}</div>}
      </form>
    </Modal>
  );
}

function DeleteTenant({ tenant, onClose, onDeleted }: { tenant: Tenant; onClose: () => void; onDeleted: () => void }) {
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function remove() {
    setBusy(true);
    try {
      await api(`/tenants/${tenant.id}`, { method: "DELETE", body: { confirm_name: typed } });
      onDeleted();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <Modal danger title={`Delete the tenant ${tenant.name}?`} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-danger" disabled={busy || typed !== tenant.name} onClick={remove}><Icon name="trash" />Delete tenant</button></>}>
      <p style={{ margin: 0 }}>This cannot be undone. It deletes:</p>
      <ul style={{ margin: 0, paddingLeft: 20 }}>
        <li>the tenant's users and pending invitations</li>
        <li>its documents, versions and vector index (when available)</li>
        <li>its chats, LLM and integration settings (when available)</li>
      </ul>
      <p className="muted small" style={{ margin: 0 }}>The logs are kept according to retention.</p>
      <label className="field">Type the tenant name to confirm
        <input className="input" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={tenant.name} autoFocus />
      </label>
      {error && <div className="error" role="alert">{error}</div>}
    </Modal>
  );
}
