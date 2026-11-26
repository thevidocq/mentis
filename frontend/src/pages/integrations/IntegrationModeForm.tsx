import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";

type Mode = "standard" | "tools";
interface State { mode: Mode; editable: boolean; reason: string | null; own_llm: boolean }

const MODES: [Mode, string, string][] = [
  ["standard", "Standard",
    "Mentis chooses the lookups before reading any customer data: ticket numbers and alert ids are read directly, and one short call to the AI model adds host, user and search lookups. Works with every AI model. Lookups do not build on each other: to follow a host named in a ticket, the analyst asks a follow-up question."],
  ["tools", "Function calling",
    "The AI model reads each result and can ask for further lookups, for example the host named in a ticket and then that host's alerts, up to 3 steps and 8 lookups per question. Needs a model with function calling (Anthropic, OpenAI, and vLLM or Ollama models that support it); otherwise Mentis falls back to Standard. Text inside tickets and alerts can influence the next lookup: at most an extra read of this customer's data, always read only and logged."],
];

/** How integration lookups are chosen for a customer: standard (planned once) or function calling. */
export function IntegrationModeForm({ tenantId }: { tenantId: string }) {
  const [state, setState] = useState<State | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<State>(`/tenants/${tenantId}/integration-mode`).then(setState).catch((e) => setMsg({ ok: false, text: errorText(e) }));
  }, [tenantId]);

  async function choose(mode: Mode) {
    if (!state || busy || !state.editable || mode === state.mode) return;
    setBusy(true);
    setMsg(null);
    try {
      setState(await api<State>(`/tenants/${tenantId}/integration-mode`, { method: "PUT", body: { mode } }));
      setMsg({ ok: true, text: "Saved. It applies to the next questions." });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  if (!state) return msg ? <div className="error">{msg.text}</div> : null;
  return (
    <div className="stack" style={{ gap: 8 }}>
      <strong>Integration lookups</strong>
      <span className="muted small">How Mentis decides what to read in the customer's tools when an analyst uses integrations with #.</span>
      <div className="mode-options" role="radiogroup" aria-label="Integration lookups">
        {MODES.map(([m, title, text]) => (
          <button key={m} type="button" role="radio" aria-checked={state.mode === m} disabled={!state.editable || busy}
            className={`role-card${state.mode === m ? " on" : ""}`} onClick={() => choose(m)}>
            <span className="role-radio" aria-hidden="true" />
            <span><strong>{title}{m === "standard" && <span className="pill accent" style={{ marginLeft: 8 }}>default</span>}</strong>
              <span className="muted small">{text}</span></span>
          </button>
        ))}
      </div>
      {state.reason && <div className="muted small">{state.reason}</div>}
      {msg && <div className={msg.ok ? "notice" : "error"} role="status">{msg.text}</div>}
    </div>
  );
}
