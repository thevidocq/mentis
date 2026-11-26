import { useState } from "react";
import type { ChatMessage } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Markdown } from "../../components/Markdown";
import { SourcesBar } from "./Sources";

export function UserMessage({ m }: { m: Pick<ChatMessage, "content"> }) {
  return <div className="msg-user"><div className="bubble">{m.content}</div></div>;
}

interface Props {
  m: ChatMessage;
  onFollowup?: (q: string) => void;   // absent: read-only (a shared chat)
  onFeedback?: (value: 1 | -1 | null) => void;
  onRetry?: () => void;
  busy: boolean;
  onSources: (n: number | null) => void; // open the sources panel (on section n)
  sourcesOpen: boolean;
}

export function AssistantMessage({ m, onFollowup, onFeedback, onRetry, busy, onSources, sourcesOpen }: Props) {
  const [copied, setCopied] = useState(false);
  // [n] in the text: open the sources panel on that section.
  const toggle = (n: number) => onSources(n);

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
        {m.tenants.map((t) => <span key={t} className={`pill${t === "General Knowledge Base" || t.startsWith("All ") ? "" : " accent"}`}>{t}</span>)}
        {m.status === "not_found" && <span className="pill warn">Not found</span>}
      </div>
      <div className={m.status === "not_found" ? "answer not-found" : "answer"}>
        <Markdown source={m.content} cite={cite} />
      </div>
      {m.citations.length > 0 && (
        <SourcesBar citations={m.citations} active={sourcesOpen} onOpen={() => onSources(null)} />
      )}
      {m.followups.length > 0 && onFollowup && (
        <div className="followups">
          {m.followups.map((f) => (
            <button key={f} type="button" className="followup" disabled={busy} onClick={() => onFollowup(f)}>
              <Icon name="chevronRight" size={14} />{f}
            </button>
          ))}
        </div>
      )}
      <div className="answer-foot">
        {onFeedback && <>
          <button className={`icon-btn${m.feedback === 1 ? " on" : ""}`} style={{ border: 0 }} aria-label="Helpful" aria-pressed={m.feedback === 1}
            onClick={() => onFeedback(m.feedback === 1 ? null : 1)}><Icon name="thumbUp" size={15} /></button>
          <button className={`icon-btn${m.feedback === -1 ? " on" : ""}`} style={{ border: 0 }} aria-label="Not helpful" aria-pressed={m.feedback === -1}
            onClick={() => onFeedback(m.feedback === -1 ? null : -1)}><Icon name="thumbDown" size={15} /></button>
        </>}
        <button className="icon-btn" style={{ border: 0 }} aria-label="Copy answer"
          onClick={() => { navigator.clipboard?.writeText(m.content).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => undefined); }}>
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
