import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorText } from "../api/client";
import { Brand } from "../components/Logo";
import { PasswordFields, passwordProblem } from "../components/PasswordFields";

/** "Forgot password?" from the sign-in page: asks for a link by email. */
export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ detail: string }>("/auth/password/forgot", { method: "POST", body: { email: email.trim() } });
      setSent(r.detail);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-page">
      <Brand />
      <form className="card auth-card" onSubmit={submit}>
        <div className="card-head"><h2>Forgot password</h2></div>
        <div className="card-body stack">
          {sent ? (
            <>
              <p style={{ margin: 0 }}>{sent}</p>
              <p className="muted small" style={{ margin: 0 }}>
                The link works once and expires soon. No email? Ask your administrator for a reset link.
              </p>
            </>
          ) : (
            <>
              <p className="muted" style={{ margin: 0 }}>Enter your email: you will receive a link to choose a new password. You will still need your authenticator app to sign in.</p>
              <label className="field">Email
                <input className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
              </label>
              {error && <div className="error" role="alert">{error}</div>}
              <button className="btn btn-primary" disabled={busy}>Send link</button>
            </>
          )}
          <Link className="link-btn small" to="/login">Back to sign in</Link>
        </div>
      </form>
    </div>
  );
}

/** The link from the email (or from an admin): choose the new password. */
export function ResetPassword() {
  const { token = "" } = useParams();
  const [email, setEmail] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ email: string }>(`/auth/password/reset/${encodeURIComponent(token)}`).then((r) => setEmail(r.email)).catch((e) => setLoadError(errorText(e)));
  }, [token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problem = passwordProblem(password, confirm);
    if (problem) return setError(problem);
    setBusy(true);
    setError(null);
    try {
      await api(`/auth/password/reset/${encodeURIComponent(token)}`, { method: "POST", body: { password } });
      setDone(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-page">
      <Brand />
      <div className="card auth-card">
        <div className="card-head"><h2>Choose a new password</h2></div>
        <div className="card-body stack">
          {loadError && (
            <>
              <div className="error" role="alert">{loadError}</div>
              <Link className="btn" to="/forgot">Ask for a new link</Link>
            </>
          )}
          {!loadError && !email && <div className="muted">Loading…</div>}
          {email && !done && (
            <form className="stack" onSubmit={submit}>
              <label className="field">Email
                <input className="input" value={email} readOnly autoComplete="username" />
              </label>
              <PasswordFields password={password} confirm={confirm} onPassword={setPassword} onConfirm={setConfirm} label="New password" />
              {error && <div className="error" role="alert">{error}</div>}
              <button className="btn btn-primary" disabled={busy}>Set password</button>
            </form>
          )}
          {done && (
            <>
              <p style={{ margin: 0 }}>Your password is changed and every open session was closed. Sign in with the new password and your authenticator app.</p>
              <Link className="btn btn-primary" to="/login">Go to sign in</Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
