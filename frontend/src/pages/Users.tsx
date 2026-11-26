import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api/client";
import { AdminUser, Invitation, InvitationCreated, ROLE_LABEL, Role, Tenant, TenantRef } from "../api/types";
import { useCurrentTenant } from "../auth/currentTenant";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { Modal } from "../components/Modal";
import { PageHead } from "../layouts/AdminShell";

// Shared by the platform admin (all users) and the tenant admin (the users it can manage).
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
  const [resetLink, setResetLink] = useState<{ email: string; url: string; hours: number } | null>(null);

  const load = useCallback(() => {
    Promise.all([api<AdminUser[]>("/users"), api<Invitation[]>("/invitations"), api<Tenant[]>("/tenants")])
      .then(([u, i, t]) => { setUsers(u); setInvites(i); setTenants(t); })
      .catch((e) => setError(errorText(e)));
  }, []);
  useEffect(load, [load]);

  const { current } = useCurrentTenant();
  const canGiveAll = isSuper || !!me?.all_tenants;
  const scope = (role: Role, list: TenantRef[], all: boolean) => {
    if (role === "super_admin") return "Platform";
    const customers = all ? "All customers (also future)" : list.filter((t) => !t.is_general).map((t) => t.name).join(", ");
    const kb = role === "tenant_admin" && list.some((t) => t.is_general) ? "manages the Knowledge Base" : "";
    return [customers, kb].filter(Boolean).join(" · ") || (role === "analyst" ? "Knowledge Base only" : "—");
  };

  async function resetTwoFactor(u: AdminUser) {
    try {
      await api(`/users/${u.id}/reset-2fa`, { method: "POST" });
      setNotice(`2FA reset for ${u.email}. They will set up the authenticator again at next sign-in.`);
      load();
    } catch (e) { setError(errorText(e)); }
  }

  async function passwordLink(u: AdminUser) {
    try {
      const r = await api<{ email_sent: boolean; reset_url: string | null; expires_hours: number }>(`/users/${u.id}/password-reset`, { method: "POST" });
      if (r.email_sent || !r.reset_url) setNotice(`A password reset link was emailed to ${u.email} (valid ${r.expires_hours} hours, once).`);
      else setResetLink({ email: u.email, url: r.reset_url, hours: r.expires_hours });
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
                  <td>{scope(u.role, u.tenants, u.all_tenants)}</td>
                  <td>
                    {!u.is_active ? <span className="pill danger">Disabled</span>
                      : u.locked ? <span className="pill warn">Locked</span>
                      : u.totp_enabled ? <span className="pill ok">Active</span>
                      : <span className="pill">2FA not set up</span>}
                  </td>
                  <td>
                    <div className="actions">
                      <button className="icon-btn" aria-label={`Edit ${u.email}`} onClick={() => setEditing(u)}><Icon name="pencil" /></button>
                      {u.id !== me?.id && u.is_active && <button className="icon-btn" aria-label={`Password reset link for ${u.email}`} title="Password reset link" onClick={() => passwordLink(u)}><Icon name="mail" /></button>}
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
                    <td>{scope(i.role, i.tenants, i.all_tenants)}</td>
                    <td className="muted">{new Date(i.expires_at).toLocaleString()}</td>
                    <td><div className="actions"><button className="icon-btn danger" aria-label={`Revoke invitation for ${i.email}`} onClick={() => revokeInvite(i)}><Icon name="trash" /></button></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {inviting && <InviteForm isSuper={isSuper} canGiveAll={canGiveAll} tenants={tenants} myTenant={current && !current.is_general ? current.id : null} onClose={() => setInviting(false)} onDone={() => load()} />}
      {editing && <EditUser user={editing} isSuper={isSuper} canGiveAll={canGiveAll} isSelf={editing.id === me?.id} tenants={tenants} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
      {resetLink && (
        <Modal title="Password reset link" onClose={() => setResetLink(null)}
          footer={<button className="btn btn-primary" onClick={() => setResetLink(null)}>Done</button>}>
          <p style={{ margin: 0 }}>Email is not configured: send this link to <strong>{resetLink.email}</strong> yourself. It works once, for {resetLink.hours} hours. Their authenticator app is still required to sign in.</p>
          <div className="notice mono">{resetLink.url}</div>
          <button className="btn" onClick={() => navigator.clipboard?.writeText(resetLink.url).catch(() => undefined)}>Copy link</button>
        </Modal>
      )}
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

interface Access { tenantIds: string[]; all: boolean }

/** Tenant ids to send: the customers (none with "all customers"), plus the General Knowledge Base
 *  only for a tenant admin who must manage it. */
function accessIds(access: Access, role: Role, tenants: Tenant[]): string[] {
  const gkb = tenants.find((t) => t.is_global)?.id;
  const customers = access.all ? [] : access.tenantIds.filter((id) => id !== gkb);
  return role === "tenant_admin" && gkb && access.tenantIds.includes(gkb) ? [...customers, gkb] : customers;
}

/** Customers of a tenant admin or an analyst (ticks or all customers), and for a tenant admin the
 *  permission to manage the General Knowledge Base. Everyone reads the knowledge base anyway. */
function AccessPicker({ tenants, value, onChange, canGiveAll, role }: {
  tenants: Tenant[]; value: Access; onChange: (a: Access) => void; canGiveAll: boolean; role: Role;
}) {
  const [q, setQ] = useState("");
  const [onlySelected, setOnlySelected] = useState(false);
  const gkb = tenants.find((t) => t.is_global);
  const customers = tenants.filter((t) => !t.is_global);
  const many = customers.length > 8;
  const needle = q.trim().toLowerCase();
  const ordered = [...customers]
    .sort((a, b) => a.name.localeCompare(b.name))
    .filter((t) => (!needle || t.name.toLowerCase().includes(needle)) && (!onlySelected || value.tenantIds.includes(t.id)));
  const toggle = (id: string) => onChange({ ...value, tenantIds: value.tenantIds.includes(id) ? value.tenantIds.filter((x) => x !== id) : [...value.tenantIds, id] });
  const picked = value.tenantIds.filter((id) => id !== gkb?.id).length;
  return (
    <>
      <fieldset className="field tenant-picker">
        <legend>Customers {value.all ? "(all)" : `(${picked} selected)`}</legend>
        {canGiveAll && (
          <label className="check all-customers">
            <input type="checkbox" checked={value.all} onChange={(e) => onChange({ ...value, all: e.target.checked })} />
            <span><strong>All customers, including future ones</strong><br /><span className="muted small">New customers are added automatically.</span></span>
          </label>
        )}
        {!value.all && many && (
          <div className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
            <input className="input" type="search" placeholder="Search customers…" aria-label="Search customers" value={q}
              onChange={(e) => setQ(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
            <label className="check small" style={{ whiteSpace: "nowrap" }}>
              <input type="checkbox" checked={onlySelected} onChange={(e) => setOnlySelected(e.target.checked)} />Selected only
            </label>
          </div>
        )}
        {!value.all && (
          <div className={many ? "tenant-picker-list" : undefined}>
            {ordered.map((t) => (
              <label key={t.id} className="check">
                <input type="checkbox" checked={value.tenantIds.includes(t.id)} onChange={() => toggle(t.id)} />
                {t.name}
              </label>
            ))}
            {ordered.length === 0 && <span className="muted small">No customer matches.</span>}
          </div>
        )}
        <span className="muted small">Everyone reads the General Knowledge Base in the chat: no tick needed.</span>
      </fieldset>
      {role === "tenant_admin" && gkb && (
        <label className="check">
          <input type="checkbox" checked={value.tenantIds.includes(gkb.id)} onChange={() => toggle(gkb.id)} />
          <span><strong>Can manage the General Knowledge Base</strong><br />
            <span className="muted small">Upload and approve the general knowledge used by every customer. Give it to SOC admins only.</span></span>
        </label>
      )}
    </>
  );
}

const ROLE_HELP: Record<Role, string> = {
  analyst: "Analyst (chat on the chosen customers)",
  tenant_admin: "Tenant admin (manages the chosen customers)",
  super_admin: "Super-admin (platform only, no customer content)",
};

function RoleAndAccess({ role, setRole, access, setAccess, tenants, isSuper, canGiveAll }: {
  role: Role; setRole: (r: Role) => void; access: Access; setAccess: (a: Access) => void; tenants: Tenant[]; isSuper: boolean; canGiveAll: boolean;
}) {
  const roles: Role[] = isSuper ? ["analyst", "tenant_admin", "super_admin"] : ["analyst", "tenant_admin"];
  return (
    <>
      <label className="field">Role
        <select className="input" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {roles.map((r) => <option key={r} value={r}>{ROLE_HELP[r]}</option>)}
        </select>
      </label>
      {role !== "super_admin" && <AccessPicker tenants={tenants} value={access} onChange={setAccess} canGiveAll={canGiveAll} role={role} />}
    </>
  );
}

function InviteForm({ isSuper, canGiveAll, tenants, myTenant, onClose, onDone }: {
  isSuper: boolean; canGiveAll: boolean; tenants: Tenant[]; myTenant: string | null; onClose: () => void; onDone: () => void;
}) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<Role>("analyst");
  // The customer the tenant admin is working on is ticked; managing the knowledge base never is by default.
  const [access, setAccess] = useState<Access>({ tenantIds: myTenant ? [myTenant] : [], all: false });
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
        body: role === "super_admin" ? { email, full_name: fullName, role }
          : { email, full_name: fullName, role, tenant_ids: accessIds(access, role, tenants), all_tenants: access.all },
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
            <button className="btn" onClick={() => navigator.clipboard?.writeText(result.invite_url ?? "").catch(() => undefined)}>Copy link</button>
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
        <RoleAndAccess role={role} setRole={setRole} access={access} setAccess={setAccess} tenants={tenants} isSuper={isSuper} canGiveAll={canGiveAll} />
        {!isSuper && <span className="muted small">You can give only the customers you have yourself.</span>}
        {error && <div className="error" role="alert">{error}</div>}
      </form>
    </Modal>
  );
}

function EditUser({ user, isSuper, canGiveAll, isSelf, tenants, onClose, onSaved }: {
  user: AdminUser; isSuper: boolean; canGiveAll: boolean; isSelf: boolean; tenants: Tenant[]; onClose: () => void; onSaved: () => void;
}) {
  const [fullName, setFullName] = useState(user.full_name);
  const [role, setRole] = useState<Role>(user.role);
  const [access, setAccess] = useState<Access>({ tenantIds: user.tenants.map((t) => t.id), all: user.all_tenants });
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
    if (!isSelf && (role !== user.role || access.all !== user.all_tenants || access.tenantIds.slice().sort().join() !== before)) {
      body.role = role;
      if (role !== "super_admin") {
        body.tenant_ids = accessIds(access, role, tenants);
        body.all_tenants = access.all;
      }
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
        {!isSelf && <RoleAndAccess role={role} setRole={setRole} access={access} setAccess={setAccess} tenants={tenants} isSuper={isSuper} canGiveAll={canGiveAll} />}
        {!isSelf && (
          <label className="check"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Account active</label>
        )}
        {error && <div className="error" role="alert">{error}</div>}
      </form>
    </Modal>
  );
}
