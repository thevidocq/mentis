import { FormEvent, useState } from "react";
import { api, errorText } from "../../api/client";
import type { DocVersion } from "../../api/types";
import { Markdown } from "../../components/Markdown";

interface Passage { score: number; page_index: number; page_label: string; heading: string | null; text: string }

/** "Test a question": the passages of this version the chat would use to answer. */
export function TestQuestion({ base, version, onOpen }: { base: string; version: DocVersion; onOpen: (pageIndex: number) => void }) {
  const [question, setQuestion] = useState("");
  const [passages, setPassages] = useState<Passage[] | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function ask(e: FormEvent) {
    e.preventDefault();
    setAsking(true);
    setError(null);
    try {
      setPassages(await api<Passage[]>(`${base}/versions/${version.id}/search`, { method: "POST", body: { question } }));
    } catch (err) {
      setError(errorText(err));
      setPassages(null);
    } finally {
      setAsking(false);
    }
  }
  if (version.status !== "ready") return <div className="doc-pad muted">Available when v{version.version} is processed.</div>;
  return (
    <div className="doc-pad stack" style={{ gap: 14 }}>
      <form className="row" style={{ gap: 10 }} onSubmit={ask}>
        <input className="input" style={{ flex: 1, minWidth: 200 }} value={question} onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Who is the on-call contact for high severity?" aria-label="Question to test" />
        <button className="btn btn-primary" disabled={asking || question.trim().length < 2}>Find passages</button>
      </form>
      <span className="muted small">Shows the passages of v{version.version} the chat would use to answer.</span>
      {error && <div className="error" role="alert">{error}</div>}
      {passages && passages.length === 0 && <span className="muted">No passage matches: the chat would answer "not found".</span>}
      {passages?.map((p, i) => (
        <div key={i} className="doc-passage">
          <div className="row small" style={{ gap: 8 }}>
            <button className="btn btn-sm" onClick={() => onOpen(p.page_index)}>{p.page_label}</button>
            {p.heading && <strong>{p.heading}</strong>}
            <span className="spacer muted">match {Math.round(p.score * 100)}%</span>
          </div>
          <Markdown source={p.text} breaks />
        </div>
      ))}
    </div>
  );
}
