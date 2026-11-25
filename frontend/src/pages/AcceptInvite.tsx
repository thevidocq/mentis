import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorText } from "../api/client";
import { ROLE_LABEL, Role } from "../api/types";
import { Brand } from "../components/Logo";
import { PasswordFields, passwordProblem } from "../components/PasswordFields";

interface Info { email: string; full_name: string; role: Role; tenant_name: string | null }

export function AcceptInvite() {
  const { token = "" } = useParams();
  const [info, setInfo] = useState<Info | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Info>(`/invitations/accept/${encodeURIComponent(token)}`).then(setInfo).catch((e) => setLoadError(errorText(e)));
  }, [token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problem = passwordProblem(password, confirm);
    if (problem) return setError(problem);
    setBusy(true);
    setError(null);
    try {
      await api(`/invitations/accept/${encodeURIComponent(token)}`, { method: "POST", body: { password } });
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
        <div className="card-head"><h2>Accept invitation</h2></div>
        <div className="card-body stack">
          {loadError && <div className="error" role="alert">{loadError}</div>}
          {!loadError && !info && <div className="muted">Loading…</div>}
          {info && !done && (
            <form className="stack" onSubmit={submit}>
              <p style={{ margin: 0 }}>
                Welcome {info.full_name}. You are joining as <strong>{ROLE_LABEL[info.role]}</strong>
                {info.tenant_name ? <> for <strong>{info.tenant_name}</strong></> : null}.
              </p>
              <label className="field">Email
                <input className="input" value={info.email} readOnly autoComplete="username" />
              </label>
              <PasswordFields password={password} confirm={confirm} onPassword={setPassword} onConfirm={setConfirm} label="Password" />
              {error && <div className="error" role="alert">{error}</div>}
              <button className="btn btn-primary" disabled={busy}>Set password</button>
            </form>
          )}
          {done && (
            <>
              <p style={{ margin: 0 }}>Your account is ready. At your first sign-in you will set up two-factor authentication.</p>
              <Link className="btn btn-primary" to="/login">Go to sign in</Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
