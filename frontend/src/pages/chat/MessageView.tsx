import { useState } from "react";
import type { ChatMessage, Citation } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Markdown, placedMarks } from "../../components/Markdown";
import { CheckFlag, CheckNotes, checkMarks, markedIssues } from "./CheckNotes";
import { recordLinks, SourcesBar } from "./Sources";

/** Pages of the live records cited by an answer: the only addresses shown as links in it. */
function recordUrls(citations: Citation[]): Set<string> | undefined {
  const urls = citations.flatMap((c) => (c.kind === "integration" ? recordLinks(c).map(([, url]) => url) : []));
  return urls.length ? new Set(urls) : undefined;
}

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

  // Answer check: each problem underlined in the text, with a small ⚠ after its citations.
  const issues = markedIssues(m.check);
  const marks = checkMarks(m.check);
  const flag = (k: number, cites: number[], key: string) =>
    issues[k] ? <CheckFlag key={key} issue={issues[k]} cites={cites} onPassage={(n) => toggle(n)} /> : null;

  return (
    <div className="msg-assistant answer-card">
      <div className="answer-meta">
        <span className="answer-dot" aria-hidden="true" />
        <span>{m.tenants.join(" · ")}</span>
        {m.status === "not_found" && <span className="answer-flag">Not found</span>}
      </div>
      <div className={m.status === "not_found" ? "answer not-found" : "answer"}>
        <Markdown source={m.content} cite={cite} marks={marks} flag={flag} links={recordUrls(m.citations)} />
      </div>
      {m.citations.length > 0 && (
        <SourcesBar citations={m.citations} active={sourcesOpen} onOpen={() => onSources(null)} />
      )}
      <CheckNotes check={m.check} placed={marks.length ? placedMarks(m.content, marks) : []} />
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
          <span className="muted small answer-model" title={m.model ?? ""}>
            {m.provider_name}{m.latency_ms != null ? ` · ${(m.latency_ms / 1000).toFixed(1)} s` : ""}
            {m.check?.checker && m.check.level2 !== "off" ? (m.check.checker.name === m.provider_name
              ? <span title="No separate model checks the answers: the model that wrote this answer re-read it against its sources."> · self-checked by {m.check.checker.name}</span>
              : ` · checked by ${m.check.checker.name}`) : ""}
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
