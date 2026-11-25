import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorText } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "../components/Logo";
import { PasswordFields, passwordProblem } from "../components/PasswordFields";

export function Setup() {
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problem = passwordProblem(password, confirm);
    if (problem) return setError(problem);
    setBusy(true);
    setError(null);
    try {
      await api("/setup", { method: "POST", body: { email, full_name: fullName, password } });
      await refresh();
      navigate("/login", { replace: true });
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
        <div className="card-head"><h2>First-run setup</h2></div>
        <div className="card-body stack">
          <p className="muted" style={{ margin: 0 }}>Create the super-admin account. This page is shown only once.</p>
          <label className="field">Full name
            <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} required autoFocus />
          </label>
          <label className="field">Email
            <input className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <PasswordFields password={password} confirm={confirm} onPassword={setPassword} onConfirm={setConfirm} />
          {error && <div className="error" role="alert">{error}</div>}
          <button className="btn btn-primary" disabled={busy}>Create super-admin</button>
        </div>
      </form>
    </div>
  );
}
