import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api/client";
import { AdminUser, Invitation, InvitationCreated, ROLE_LABEL, Role, Tenant, TenantRef } from "../api/types";
import { useCurrentTenant } from "../auth/currentTenant";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { Modal } from "../components/Modal";
import { PageHead } from "../layouts/AdminShell";

// Shared by the platform admin (all users) and the tenant admin (admins of its own tenants).
export function Users() {
  const { user: me } = useAuth();
  const isSuper = me?.role === "super_admin";
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [invites, setInvites] = useState<Invitation[]>([]);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [deleting, setDeleting] = useState<AdminUser | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([api<AdminUser[]>("/users"), api<Invitation[]>("/invitations"), api<Tenant[]>("/tenants")])
      .then(([u, i, t]) => { setUsers(u); setInvites(i); setTenants(t); })
      .catch((e) => setError(errorText(e)));
  }, []);
  useEffect(load, [load]);

  const { current } = useCurrentTenant();
  const scope = (role: Role, list: TenantRef[]) =>
    role === "super_admin" ? "Platform" : role === "analyst" ? "All customers" : list.map((t) => t.name).join(", ") || "—";

  async function resetTwoFactor(u: AdminUser) {
    try {
      await api(`/users/${u.id}/reset-2fa`, { method: "POST" });
      setNotice(`2FA reset for ${u.email}. They will set up the authenticator again at next sign-in.`);
      load();
    } catch (e) { setError(errorText(e)); }
  }

  async function revokeInvite(inv: Invitation) {
    try { await api(`/invitations/${inv.id}`, { method: "DELETE" }); load(); } catch (e) { setError(errorText(e)); }
  }

  return (
    <>
      <PageHead title="Users">
        <span className="muted">{users.length} {users.length === 1 ? "user" : "users"} · {invites.length} pending {invites.length === 1 ? "invitation" : "invitations"}</span>
        <button className="btn btn-primary spacer" onClick={() => setInviting(true)}><Icon name="mail" />Invite user</button>
      </PageHead>
      <div className="page-body">
        {error && <div className="error">{error}</div>}
        {notice && <div className="notice">{notice}</div>}
        <div className="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Role</th><th>Scope</th><th>Status</th><th style={{ textAlign: "right" }}>Actions</th></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td><strong>{u.full_name}</strong><div className="muted small">{u.email}</div></td>
                  <td>{ROLE_LABEL[u.role]}</td>
                  <td>{scope(u.role, u.tenants)}</td>
                  <td>
                    {!u.is_active ? <span className="pill danger">Disabled</span>
                      : u.locked ? <span className="pill warn">Locked</span>
                      : u.totp_enabled ? <span className="pill ok">Active</span>
                      : <span className="pill">2FA not set up</span>}
                  </td>
                  <td>
                    <div className="actions">
                      {!u.manageable && <span className="muted small" title="This admin also manages customers that are not yours">other customers</span>}
                      <button className="icon-btn" aria-label={`Edit ${u.email}`} disabled={!u.manageable} onClick={() => setEditing(u)}><Icon name="pencil" /></button>
                      {isSuper && <button className="icon-btn" aria-label={`Reset 2FA for ${u.email}`} title="Reset 2FA" onClick={() => resetTwoFactor(u)}><Icon name="key" /></button>}
                      <button className="icon-btn danger" aria-label={`Delete ${u.email}`} disabled={u.id === me?.id || !u.manageable} onClick={() => setDeleting(u)}><Icon name="trash" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {invites.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Pending invitation</th><th>Role</th><th>Scope</th><th>Expires</th><th style={{ textAlign: "right" }}>Actions</th></tr></thead>
              <tbody>
                {invites.map((i) => (
                  <tr key={i.id}>
                    <td><strong>{i.full_name}</strong><div className="muted small">{i.email}</div></td>
                    <td>{ROLE_LABEL[i.role]}</td>
                    <td>{scope(i.role, i.tenants)}</td>
                    <td className="muted">{new Date(i.expires_at).toLocaleString()}</td>
                    <td><div className="actions"><button className="icon-btn danger" aria-label={`Revoke invitation for ${i.email}`} onClick={() => revokeInvite(i)}><Icon name="trash" /></button></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {inviting && <InviteForm isSuper={isSuper} tenants={tenants} myTenant={current?.id ?? null} onClose={() => setInviting(false)} onDone={() => load()} />}
      {editing && <EditUser user={editing} isSuper={isSuper} isSelf={editing.id === me?.id} tenants={tenants} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
      {deleting && (
        <Modal danger title={`Delete ${deleting.full_name}?`} onClose={() => setDeleting(null)}
          footer={<><button className="btn" onClick={() => setDeleting(null)}>Cancel</button>
            <button className="btn btn-danger" onClick={async () => {
              try { await api(`/users/${deleting.id}`, { method: "DELETE" }); setDeleting(null); load(); }
              catch (e) { setDeleting(null); setError(errorText(e)); }
            }}><Icon name="trash" />Delete user</button></>}>
          <p style={{ margin: 0 }}>{deleting.email} loses access immediately. This cannot be undone.</p>
        </Modal>
      )}
    </>
  );
}

function TenantPicker({ tenants, selected, onChange }: { tenants: Tenant[]; selected: string[]; onChange: (ids: string[]) => void }) {
  const customers = tenants.filter((t) => !t.is_global);
  const toggle = (id: string) => onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  return (
    <fieldset className="field tenant-picker">
      <legend>Customers ({selected.length} selected)</legend>
      {customers.length === 0 && <span className="muted small">No customer tenant yet.</span>}
      {customers.map((t) => (
        <label key={t.id} className="check"><input type="checkbox" checked={selected.includes(t.id)} onChange={() => toggle(t.id)} />{t.name}</label>
      ))}
    </fieldset>
  );
}

function RoleAndTenants({ role, setRole, tenantIds, setTenantIds, tenants }: {
  role: Role; setRole: (r: Role) => void; tenantIds: string[]; setTenantIds: (t: string[]) => void; tenants: Tenant[];
}) {
  return (
    <>
      <label className="field">Role
        <select className="input" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          <option value="analyst">Analyst (chat, all customers)</option>
          <option value="tenant_admin">Tenant admin (chosen customers)</option>
          <option value="super_admin">Super-admin (platform)</option>
        </select>
      </label>
      {role === "tenant_admin" && <TenantPicker tenants={tenants} selected={tenantIds} onChange={setTenantIds} />}
    </>
  );
}

function InviteForm({ isSuper, tenants, myTenant, onClose, onDone }: {
  isSuper: boolean; tenants: Tenant[]; myTenant: string | null; onClose: () => void; onDone: () => void;
}) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<Role>(isSuper ? "analyst" : "tenant_admin");
  const [tenantIds, setTenantIds] = useState<string[]>(myTenant ? [myTenant] : []);
  const [result, setResult] = useState<InvitationCreated | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<InvitationCreated>("/invitations", {
        method: "POST",
        body: { email, full_name: fullName, role, tenant_ids: role === "tenant_admin" ? tenantIds : [] },
      });
      setResult(r);
      onDone();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <Modal title="Invitation created" onClose={onClose} footer={<button className="btn btn-primary" onClick={onClose}>Done</button>}>
        {result.email_sent ? (
          <p style={{ margin: 0 }}>An email with the invitation link was sent to <strong>{result.email}</strong>. The link is valid for 72 hours.</p>
        ) : (
          <>
            <p style={{ margin: 0 }}>Email is not configured (or sending failed), so share this link with <strong>{result.email}</strong> yourself. It works once and expires in 72 hours.</p>
            <div className="notice mono">{result.invite_url}</div>
            <button className="btn" onClick={() => navigator.clipboard?.writeText(result.invite_url ?? "")}>Copy link</button>
          </>
        )}
      </Modal>
    );
  }

  return (
    <Modal title="Invite user" onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="invite-form" disabled={busy}>Send invitation</button></>}>
      <form id="invite-form" className="stack" onSubmit={submit}>
        <label className="field">Full name<input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} required autoFocus /></label>
        <label className="field">Email<input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        {isSuper
          ? <RoleAndTenants role={role} setRole={setRole} tenantIds={tenantIds} setTenantIds={setTenantIds} tenants={tenants} />
          : <>
              <span className="muted small">The new user will be a tenant admin. Choose which of your customers.</span>
              <TenantPicker tenants={tenants} selected={tenantIds} onChange={setTenantIds} />
            </>}
        {error && <div className="error" role="alert">{error}</div>}
      </form>
    </Modal>
  );
}

function EditUser({ user, isSuper, isSelf, tenants, onClose, onSaved }: {
  user: AdminUser; isSuper: boolean; isSelf: boolean; tenants: Tenant[]; onClose: () => void; onSaved: () => void;
}) {
  const [fullName, setFullName] = useState(user.full_name);
  const [role, setRole] = useState<Role>(user.role);
  const [tenantIds, setTenantIds] = useState<string[]>(user.tenants.map((t) => t.id));
  const [active, setActive] = useState(user.is_active);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = {};
    if (fullName !== user.full_name) body.full_name = fullName;
    if (active !== user.is_active) body.is_active = active;
    const before = user.tenants.map((t) => t.id).sort().join();
    if (isSuper && (role !== user.role || (role === "tenant_admin" && tenantIds.slice().sort().join() !== before))) {
      body.role = role;
      body.tenant_ids = role === "tenant_admin" ? tenantIds : [];
    }
    try {
      await api(`/users/${user.id}`, { method: "PATCH", body });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Edit ${user.full_name}`} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" form="edit-user" disabled={busy}>Save</button></>}>
      <form id="edit-user" className="stack" onSubmit={submit}>
        <div className="muted small">{user.email}</div>
        <label className="field">Full name<input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} required /></label>
        {isSuper && <RoleAndTenants role={role} setRole={setRole} tenantIds={tenantIds} setTenantIds={setTenantIds} tenants={tenants} />}
        {!isSelf && (
          <label className="check"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Account active</label>
        )}
        {error && <div className="error" role="alert">{error}</div>}
      </form>
    </Modal>
  );
}
