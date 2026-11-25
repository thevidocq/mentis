import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api/client";
import { AdminUser, Invitation, InvitationCreated, ROLE_LABEL, Role, Tenant } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { Modal } from "../components/Modal";
import { PageHead } from "../layouts/AdminShell";

// Shared by the platform admin (all users) and the tenant admin (admins of its own tenant).
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

  const tenantName = (id: string | null) => (id ? tenants.find((t) => t.id === id)?.name ?? "—" : "All customers");

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
                  <td>{u.role === "super_admin" ? "Platform" : tenantName(u.tenant_id)}</td>
                  <td>
                    {!u.is_active ? <span className="pill danger">Disabled</span>
                      : u.locked ? <span className="pill warn">Locked</span>
                      : u.totp_enabled ? <span className="pill ok">Active</span>
                      : <span className="pill">2FA not set up</span>}
                  </td>
                  <td>
                    <div className="actions">
                      <button className="icon-btn" aria-label={`Edit ${u.email}`} onClick={() => setEditing(u)}><Icon name="pencil" /></button>
                      {isSuper && <button className="icon-btn" aria-label={`Reset 2FA for ${u.email}`} title="Reset 2FA" onClick={() => resetTwoFactor(u)}><Icon name="key" /></button>}
                      <button className="icon-btn danger" aria-label={`Delete ${u.email}`} disabled={u.id === me?.id} onClick={() => setDeleting(u)}><Icon name="trash" /></button>
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
                    <td>{i.role === "super_admin" ? "Platform" : tenantName(i.tenant_id)}</td>
                    <td className="muted">{new Date(i.expires_at).toLocaleString()}</td>
                    <td><div className="actions"><button className="icon-btn danger" aria-label={`Revoke invitation for ${i.email}`} onClick={() => revokeInvite(i)}><Icon name="trash" /></button></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {inviting && <InviteForm isSuper={isSuper} tenants={tenants} myTenant={me?.tenant_id ?? null} onClose={() => setInviting(false)} onDone={() => load()} />}
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

function RoleAndTenant({ role, setRole, tenantId, setTenantId, tenants }: {
  role: Role; setRole: (r: Role) => void; tenantId: string; setTenantId: (t: string) => void; tenants: Tenant[];
}) {
  const customers = tenants.filter((t) => !t.is_global);
  return (
    <>
      <label className="field">Role
        <select className="input" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          <option value="analyst">Analyst (chat, all customers)</option>
          <option value="tenant_admin">Tenant admin (one customer)</option>
          <option value="super_admin">Super-admin (platform)</option>
        </select>
      </label>
      {role === "tenant_admin" && (
        <label className="field">Customer
          <select className="input" value={tenantId} onChange={(e) => setTenantId(e.target.value)} required>
            <option value="">Choose…</option>
            {customers.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </label>
      )}
    </>
  );
}

function InviteForm({ isSuper, tenants, myTenant, onClose, onDone }: {
  isSuper: boolean; tenants: Tenant[]; myTenant: string | null; onClose: () => void; onDone: () => void;
}) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<Role>(isSuper ? "analyst" : "tenant_admin");
  const [tenantId, setTenantId] = useState(myTenant ?? "");
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
        body: { email, full_name: fullName, role, tenant_id: role === "tenant_admin" ? tenantId || null : null },
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
          ? <RoleAndTenant role={role} setRole={setRole} tenantId={tenantId} setTenantId={setTenantId} tenants={tenants} />
          : <span className="muted small">The new user will be a tenant admin of your customer.</span>}
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
  const [tenantId, setTenantId] = useState(user.tenant_id ?? "");
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
    if (isSuper && (role !== user.role || (tenantId || null) !== user.tenant_id)) {
      body.role = role;
      body.tenant_id = role === "tenant_admin" ? tenantId || null : null;
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
        {isSuper && <RoleAndTenant role={role} setRole={setRole} tenantId={tenantId} setTenantId={setTenantId} tenants={tenants} />}
        {!isSelf && (
          <label className="check"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Account active</label>
        )}
        {error && <div className="error" role="alert">{error}</div>}
      </form>
    </Modal>
  );
}
