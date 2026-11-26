import { KeyboardEvent, useEffect, useRef, useState } from "react";
import type { ScopeOption } from "../../api/types";
import { Icon } from "../../components/Icon";

interface Props {
  scopes: ScopeOption[];
  scope: ScopeOption | null;
  locked: boolean;          // the chat already has messages: the customer cannot change
  disabled: boolean;        // waiting for an answer, or the customer is no longer available
  disabledReason?: string;
  onScope: (s: ScopeOption) => void;
  onSend: (text: string) => void;
  useGeneral: boolean;      // the General Knowledge Base is searched with the customer
  onUseGeneral: (v: boolean) => void;
}

const AT = /(^|\s)@([^\s@]*)$/;

export function Composer({ scopes, scope, locked, disabled, disabledReason, onScope, onSend, useGeneral, onUseGeneral }: Props) {
  const [confirmOff, setConfirmOff] = useState(false);
  const gkbScope = scopes.find((s) => s.is_general);
  // Asking the knowledge base alone: no separate switch for it.
  const showGeneral = !!gkbScope && !!scope && scope.id !== gkbScope.id;
  const [text, setText] = useState("");
  const [picker, setPicker] = useState<{ filter: string } | null>(null);
  const [hi, setHi] = useState(0);
  const ta = useRef<HTMLTextAreaElement>(null);

  const options = picker ? scopes.filter((s) => s.name.toLowerCase().includes(picker.filter.toLowerCase())) : [];

  useEffect(() => {
    const el = ta.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [text]);

  useEffect(() => { if (!disabled) ta.current?.focus(); }, [disabled]);

  function change(v: string) {
    setText(v);
    const m = AT.exec(v);
    setPicker(m ? { filter: m[2] } : null);
    setHi(0);
  }

  function choose(s: ScopeOption) {
    if (locked) return;
    onScope(s);
    setText((t) => t.replace(AT, "$1"));
    setPicker(null);
    ta.current?.focus();
  }

  function send() {
    const q = text.replace(AT, "$1").trim();
    if (!q || disabled) return;
    onSend(q);
    setText("");
    setPicker(null);
  }

  function key(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (picker && !locked && options.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => (h + 1) % options.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => (h - 1 + options.length) % options.length); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); choose(options[hi]); return; }
    }
    if (picker && e.key === "Escape") { setPicker(null); return; }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  return (
    <div className="composer-wrap">
      {picker && (
        <div className={`scope-picker${locked ? " locked" : ""}`} role="listbox" aria-label="Customers">
          {locked && (
            <div className="scope-picker-note"><Icon name="lock" size={14} />Customer locked for this chat. Start a new chat to ask about another customer.</div>
          )}
          {options.length === 0 && <div className="muted small" style={{ padding: "8px 12px" }}>No customer matches.</div>}
          {options.map((s, i) => (
            <button key={s.id ?? "all"} type="button" role="option" aria-selected={scope?.id === s.id} disabled={locked}
              className={`${i === hi && !locked ? "hi" : ""}${scope?.id === s.id ? " current" : ""}`}
              onMouseDown={(e) => { e.preventDefault(); choose(s); }}>
              <Icon name={s.id ? "tenants" : "users"} size={14} />{s.name}
              {scope?.id === s.id && <span className="spacer muted small">selected</span>}
            </button>
          ))}
        </div>
      )}
      <div className={`composer${disabled ? " busy" : ""}`}>
        <textarea ref={ta} rows={1} value={text} aria-label="Question" maxLength={4000}
          placeholder={disabledReason ?? (locked ? "Ask a follow-up…" : "Ask about a procedure… type @ to choose the customer")}
          disabled={disabled && !!disabledReason}
          onChange={(e) => change(e.target.value)} onKeyDown={key} onBlur={() => setTimeout(() => setPicker(null), 120)} />
        <div className="composer-bar">
          <button type="button" className={`scope-chip${locked ? " locked" : ""}`} aria-label={locked ? `Customer: ${scope?.name}, locked` : "Choose customer"}
            title={locked ? "Customer locked for this chat" : "Choose the customer (or type @)"}
            onClick={() => { if (!locked) { setPicker(picker ? null : { filter: "" }); ta.current?.focus(); } }}>
            <Icon name={locked ? "lock" : "at"} size={14} />{scope?.name ?? "Choose customer"}
          </button>
          {showGeneral && (
            <span className="gkb-switch">
              <button type="button" className={`scope-chip${useGeneral ? " on" : " off"}`} aria-pressed={useGeneral}
                aria-label={useGeneral ? "General Knowledge Base: on" : "General Knowledge Base: off"}
                title={useGeneral ? "Answers also use the General Knowledge Base" : "The General Knowledge Base is not used in this chat"}
                onClick={() => (useGeneral ? setConfirmOff(!confirmOff) : onUseGeneral(true))}>
                <Icon name={useGeneral ? "check" : "x"} size={14} />Knowledge Base
              </button>
              {confirmOff && (
                <span className="gkb-confirm" role="dialog" aria-label="Turn off the General Knowledge Base">
                  <span className="small">Answers will use only the customer's documents, without the General Knowledge Base.</span>
                  <span className="row" style={{ gap: 6 }}>
                    <button type="button" className="btn btn-sm" onClick={() => setConfirmOff(false)}>Keep it</button>
                    <button type="button" className="btn btn-sm btn-danger" onClick={() => { setConfirmOff(false); onUseGeneral(false); }}>Turn off for this chat</button>
                  </span>
                </span>
              )}
            </span>
          )}
          <button type="button" className="scope-chip" disabled title="Integrations (ticketing, EDR, SIEM): coming in a later release">
            <Icon name="hash" size={14} />Integrations<span className="muted small">soon</span>
          </button>
          <span className="spacer muted small composer-hint">Enter to send · Shift+Enter new line</span>
          <button type="button" className="btn btn-primary btn-sm composer-send" aria-label="Send" disabled={disabled || !text.replace(AT, "$1").trim()} onClick={send}>
            <Icon name="send" />
          </button>
        </div>
      </div>
    </div>
  );
}
