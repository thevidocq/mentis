// Shared password + confirmation fields with the same rules the API enforces.

export function passwordProblem(pw: string, confirm: string): string | null {
  if (pw.length < 12) return "At least 12 characters.";
  if (pw.length > 256) return "At most 256 characters.";
  if (pw.toLowerCase() === pw || pw.toUpperCase() === pw) return "Mix upper and lower case letters.";
  if (!/\d/.test(pw)) return "Include at least one digit.";
  if (pw !== confirm) return "The two passwords do not match.";
  return null;
}

interface Props {
  password: string;
  confirm: string;
  onPassword: (v: string) => void;
  onConfirm: (v: string) => void;
  label?: string;
}

export function PasswordFields({ password, confirm, onPassword, onConfirm, label = "Password" }: Props) {
  return (
    <>
      <label className="field">{label}
        <input className="input" type="password" autoComplete="new-password" value={password} onChange={(e) => onPassword(e.target.value)} />
      </label>
      <label className="field">Confirm {label.toLowerCase()}
        <input className="input" type="password" autoComplete="new-password" value={confirm} onChange={(e) => onConfirm(e.target.value)} />
      </label>
      <span className="muted small">At least 12 characters, upper and lower case, at least one digit.</span>
    </>
  );
}
