import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorText } from "../api/client";
import { ROLE_LABEL, Theme, User } from "../api/types";
import { applyTheme, homePath, useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { Brand } from "../components/Logo";
import { PasswordFields, passwordProblem } from "../components/PasswordFields";

const THEMES: { id: Theme; label: string; bg: string; side: string; body: string }[] = [
  { id: "light", label: "Light", bg: "#F8FAFC", side: "#FFFFFF", body: "#E2E8F0" },
  { id: "medium", label: "Medium", bg: "#2B3342", side: "#252C3A", body: "#46516A" },
  { id: "dark", label: "Dark", bg: "#0B1220", side: "#0F172A", body: "#1E293B" },
];

export function Account() {
  const { user, setUser, logout } = useAuth();
  const navigate = useNavigate();
  const [editingName, setEditingName] = useState(false);
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(user?.preferences?.theme ?? "dark");
  if (!user) return null;

  async function patchMe(body: Record<string, string>) {
    try {
      setUser(await api<User>("/auth/me", { method: "PATCH", body }));
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function chooseTheme(t: Theme) {
    setTheme(t); // optimistic: the page switches at once, the server call follows
    applyTheme(t);
    await patchMe({ theme: t });
  }

  async function saveName(e: FormEvent) {
    e.preventDefault();
    await patchMe({ full_name: fullName });
    setEditingName(false);
  }

  async function changePassword(e: FormEvent) {
    e.preventDefault();
    const problem = passwordProblem(password, confirm);
    if (problem) return setPwMsg({ ok: false, text: problem });
    try {
      await api("/auth/password", { method: "POST", body: { current_password: current, new_password: password } });
      setCurrent(""); setPassword(""); setConfirm("");
      setPwMsg({ ok: true, text: "Password updated. Your other sessions were signed out." });
    } catch (err) {
      setPwMsg({ ok: false, text: errorText(err) });
    }
  }

  async function signOut() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div style={{ minHeight: "100%" }}>
      <header className="page-head" style={{ minHeight: 0, padding: "14px 32px" }}>
        <Brand />
        <Link to={homePath(user)} className="row" style={{ gap: 6, textDecoration: "none" }}><Icon name="arrowLeft" />Back</Link>
        <button className="btn btn-sm spacer" onClick={signOut}><Icon name="logout" />Sign out</button>
      </header>
      <div className="stack" style={{ maxWidth: 760, margin: "0 auto", padding: "32px 24px" }}>
        <h1>Account</h1>
        {error && <div className="error">{error}</div>}

        <section className="card">
          <div className="card-head">
            <h2 style={{ flex: 1 }}>Profile</h2>
            {!editingName && <button className="btn btn-sm" onClick={() => setEditingName(true)}><Icon name="pencil" />Edit</button>}
          </div>
          <div className="card-body">
            {editingName ? (
              <form className="row" onSubmit={saveName} style={{ alignItems: "flex-end" }}>
                <label className="field" style={{ flex: 1 }}>Full name<input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} required autoFocus /></label>
                <button className="btn btn-primary">Save</button>
                <button type="button" className="btn" onClick={() => { setEditingName(false); setFullName(user.full_name); }}>Cancel</button>
              </form>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 14 }}>
                <div><div className="muted small">Name</div>{user.full_name}</div>
                <div><div className="muted small">Email</div>{user.email}</div>
                <div><div className="muted small">Role</div>{ROLE_LABEL[user.role]}</div>
                <div><div className="muted small">Customer</div>{user.tenant_name ?? (user.role === "super_admin" ? "Platform" : "All customers")}</div>
              </div>
            )}
          </div>
        </section>

        <section className="card">
          <div className="card-head"><h2>Appearance</h2></div>
          <div className="card-body">
            <div className="theme-grid" role="radiogroup" aria-label="Theme">
              {THEMES.map((t) => (
                <label key={t.id} className={`theme-option ${theme === t.id ? "selected" : ""}`}>
                  <div className="theme-swatch" style={{ background: t.bg, border: `1px solid ${t.body}` }}>
                    <div style={{ background: t.side, border: `1px solid ${t.body}` }} />
                    <div style={{ background: t.body }} />
                  </div>
                  <span className="check"><input type="radio" name="theme" checked={theme === t.id} onChange={() => chooseTheme(t.id)} /> {t.label}</span>
                </label>
              ))}
            </div>
          </div>
        </section>

        <section className="card">
          <div className="card-head"><h2>Security</h2></div>
          <form className="card-body stack" onSubmit={changePassword}>
            <label className="field">Current password
              <input className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
            </label>
            <PasswordFields password={password} confirm={confirm} onPassword={setPassword} onConfirm={setConfirm} label="New password" />
            <div className="row">
              <span className="muted small">Two-factor authentication: <strong style={{ color: "var(--ok)" }}>{user.totp_enabled ? "active" : "not set up"}</strong></span>
              <button className="btn btn-primary spacer">Update password</button>
            </div>
            {pwMsg && <div className={pwMsg.ok ? "notice" : "error"} role="status">{pwMsg.text}</div>}
          </form>
        </section>
      </div>
    </div>
  );
}
