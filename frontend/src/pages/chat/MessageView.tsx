import { useState } from "react";
import type { ChatMessage, Citation } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Markdown } from "../../components/Markdown";

export function UserMessage({ m }: { m: Pick<ChatMessage, "content"> }) {
  return <div className="msg-user"><div className="bubble">{m.content}</div></div>;
}

function Source({ c, open, onToggle }: { c: Citation; open: boolean; onToggle: () => void }) {
  return (
    <li id={`src-${c.n}`} className={open ? "open" : ""}>
      <button type="button" className="source-head" onClick={onToggle} aria-expanded={open}>
        <span className="cite-n">{c.n}</span>
        <span className={`pill${c.is_general ? "" : " accent"}`}>{c.tenant}</span>
        <span className="source-doc">{c.document}</span>
        <span className="muted small">v{c.version} · {c.page}{c.heading && c.heading !== c.page ? ` · ${c.heading}` : ""}</span>
        <span className="spacer" /><Icon name="chevronDown" size={14} />
      </button>
      {open && <div className="source-text">{c.text}</div>}
    </li>
  );
}

interface Props {
  m: ChatMessage;
  onFollowup: (q: string) => void;
  onFeedback: (value: 1 | -1 | null) => void;
  onRetry?: () => void;
  busy: boolean;
}

export function AssistantMessage({ m, onFollowup, onFeedback, onRetry, busy }: Props) {
  const [open, setOpen] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const toggle = (n: number) => setOpen((o) => (o === n ? null : n));

  if (m.status === "error") {
    return (
      <div className="msg-assistant">
        <div className="answer-error">
          <Icon name="alert" />
          <div style={{ flex: 1 }}>{m.content}</div>
          {onRetry && <button className="btn btn-sm" disabled={busy} onClick={onRetry}><Icon name="refresh" />Retry</button>}
        </div>
      </div>
    );
  }

  const cite = (n: number, key: string) =>
    m.citations.some((c) => c.n === n)
      ? <button key={key} type="button" className="cite" aria-label={`Source ${n}`} onClick={() => toggle(n)}>{n}</button>
      : null;

  return (
    <div className="msg-assistant">
      <div className="answer-meta">
        {m.tenants.map((t) => <span key={t} className={`pill${t === "General" || t === "All customers" ? "" : " accent"}`}>{t}</span>)}
        {m.status === "not_found" && <span className="pill warn">Not found</span>}
      </div>
      <div className={m.status === "not_found" ? "answer not-found" : "answer"}>
        <Markdown source={m.content} cite={cite} />
      </div>
      {m.citations.length > 0 && (
        <div className="sources">
          <div className="eyebrow">Sources</div>
          <ol>{m.citations.map((c) => <Source key={c.n} c={c} open={open === c.n} onToggle={() => toggle(c.n)} />)}</ol>
        </div>
      )}
      {m.followups.length > 0 && (
        <div className="followups">
          {m.followups.map((f) => (
            <button key={f} type="button" className="followup" disabled={busy} onClick={() => onFollowup(f)}>
              <Icon name="chevronRight" size={14} />{f}
            </button>
          ))}
        </div>
      )}
      <div className="answer-foot">
        <button className={`icon-btn${m.feedback === 1 ? " on" : ""}`} style={{ border: 0 }} aria-label="Helpful" aria-pressed={m.feedback === 1}
          onClick={() => onFeedback(m.feedback === 1 ? null : 1)}><Icon name="thumbUp" size={15} /></button>
        <button className={`icon-btn${m.feedback === -1 ? " on" : ""}`} style={{ border: 0 }} aria-label="Not helpful" aria-pressed={m.feedback === -1}
          onClick={() => onFeedback(m.feedback === -1 ? null : -1)}><Icon name="thumbDown" size={15} /></button>
        <button className="icon-btn" style={{ border: 0 }} aria-label="Copy answer"
          onClick={() => { navigator.clipboard?.writeText(m.content).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }); }}>
          <Icon name={copied ? "check" : "copy"} size={15} />
        </button>
        {m.provider_name && (
          <span className="muted small" title={m.model ?? ""}>
            {m.provider_name}{m.latency_ms != null ? ` · ${(m.latency_ms / 1000).toFixed(1)} s` : ""}
          </span>
        )}
      </div>
    </div>
  );
}

export function Thinking({ scope }: { scope: string }) {
  return (
    <div className="msg-assistant">
      <div className="thinking" role="status"><span className="dots"><i /><i /><i /></span>Searching the documentation of {scope}…</div>
    </div>
  );
}
