import QRCode from "qrcode";
import { FormEvent, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, Link } from "react-router-dom";
import { api, errorText } from "../api/client";
import type { User } from "../api/types";
import { homePath, useAuth } from "../auth/AuthContext";
import { Brand } from "../components/Logo";

type Step = "credentials" | "enroll" | "code";

export function Login() {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [step, setStep] = useState<Step>("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [challenge, setChallenge] = useState("");
  const [secret, setSecret] = useState("");
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const enrolledFor = useRef("");

  useEffect(() => {
    // Enroll once per challenge (React StrictMode runs effects twice in development).
    if (step !== "enroll" || !challenge || enrolledFor.current === challenge) return;
    enrolledFor.current = challenge;
    api<{ secret: string; otpauth_uri: string }>("/auth/totp/enroll", { method: "POST", body: { challenge } })
      .then(async (r) => {
        setSecret(r.secret);
        setQr(await QRCode.toDataURL(r.otpauth_uri, { margin: 1, width: 200 }));
      })
      .catch((e) => setError(errorText(e)));
  }, [step, challenge]);

  async function submitCredentials(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ next_step: string; challenge: string }>("/auth/login", { method: "POST", body: { email, password } });
      setChallenge(r.challenge);
      setStep(r.next_step === "mfa_enrollment" ? "enroll" : "code");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await api<User>("/auth/totp/verify", { method: "POST", body: { challenge, code } });
      setUser(user);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : homePath(user), { replace: true });
    } catch (err) {
      setError(errorText(err));
      if (errorText(err).includes("expired")) setStep("credentials");
    } finally {
      setBusy(false);
    }
  }

  const codeField = (
    <label className="field">6-digit code
      <input className="input code-input" inputMode="numeric" autoComplete="one-time-code" maxLength={8}
        value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} autoFocus required />
    </label>
  );

  return (
    <div className="center-page">
      <Brand />
      {step === "credentials" && (
        <form className="card auth-card" onSubmit={submitCredentials}>
          <div className="card-head"><h2>Sign in</h2></div>
          <div className="card-body stack">
            <label className="field">Email
              <input className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
            </label>
            <label className="field">Password
              <input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </label>
            {error && <div className="error" role="alert">{error}</div>}
            <button className="btn btn-primary" disabled={busy}>Continue</button>
            <Link className="link-btn small" to="/forgot">Forgot password?</Link>
          </div>
        </form>
      )}

      {step === "enroll" && (
        <form className="card auth-card" onSubmit={submitCode}>
          <div className="card-head"><h2>Set up two-factor authentication</h2></div>
          <div className="card-body stack">
            <p className="muted" style={{ margin: 0 }}>Scan the code with an authenticator app (Microsoft Authenticator, Google Authenticator, 1Password…), then enter the 6-digit code it shows.</p>
            {qr ? <img className="qr" src={qr} alt="QR code for the authenticator app" width={200} height={200} /> : <div className="muted">Preparing…</div>}
            {secret && <div className="small muted">Can't scan? Enter this key manually:<div className="mono" style={{ color: "var(--text)" }}>{secret}</div></div>}
            {codeField}
            {error && <div className="error" role="alert">{error}</div>}
            <button className="btn btn-primary" disabled={busy || code.length < 6}>Activate and sign in</button>
          </div>
        </form>
      )}

      {step === "code" && (
        <form className="card auth-card" onSubmit={submitCode}>
          <div className="card-head"><h2>Two-factor authentication</h2></div>
          <div className="card-body stack">
            <p className="muted" style={{ margin: 0 }}>Enter the 6-digit code from your authenticator app.</p>
            {codeField}
            {error && <div className="error" role="alert">{error}</div>}
            <button className="btn btn-primary" disabled={busy || code.length < 6}>Sign in</button>
            <button type="button" className="btn" onClick={() => { setStep("credentials"); setCode(""); setError(null); }}>Back</button>
          </div>
        </form>
      )}
    </div>
  );
}
