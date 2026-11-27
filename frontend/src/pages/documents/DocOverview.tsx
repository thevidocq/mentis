import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import { Icon } from "../../components/Icon";
import { dateText } from "./status";

interface Ver {
  document_id: string; document: string; version: number; status: string; approval: string; is_active: boolean;
  error: string | null; uploaded_at: string; processed_at?: string | null; uploaded_by?: string | null; reviewed_by?: string | null;
}
interface Overview {
  documents: number; in_use: number; needs_attention: number; pages: number; ocr_pages: number; passages: number;
  embedding_model: string; by_type: Record<string, number>; to_check: { low_confidence: number; empty: number; truncated: number };
  last_indexed: Ver | null; oldest_in_use: Ver | null; attention: Ver[]; recent: Ver[];
  questions: { answered: number; not_found: number; errors: number } | null;
}

const TYPES: [string, string, string][] = [["pdf", "PDF", "#5eead4"], ["docx", "Word", "#60a5fa"], ["pptx", "PowerPoint", "#fbbf24"], ["xlsx", "Excel", "#a78bfa"], ["md", "Markdown", "#f472b6"], ["json", "JSON", "#fb923c"], ["csv", "CSV", "#4ade80"], ["tsv", "TSV", "#a3e635"], ["yaml", "YAML", "#f87171"], ["png", "PNG", "#38bdf8"], ["jpg", "JPEG", "#818cf8"]];
const n = (x: number) => x.toLocaleString();

function stateText(v: Ver): { text: string; tone: string } {
  if (v.status === "failed") return { text: `Failed${v.error ? ` · ${v.error}` : ""}`, tone: "fail" };
  if (v.status === "link_error") return { text: v.error ?? "Link not read", tone: "fail" };
  if (v.status === "queued" || v.status === "processing") return { text: "Processing", tone: "" };
  if (v.approval === "pending") return { text: "Waiting approval", tone: "warn" };
  if (v.approval === "rejected") return { text: "Rejected", tone: "" };
  return { text: v.is_active ? "In use" : "Archived", tone: "" };
}

function ago(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days < 1) return "today";
  if (days < 45) return `${days} ${days === 1 ? "day" : "days"}`;
  const months = Math.round(days / 30);
  return months < 18 ? `${months} months` : `${Math.round(days / 365)} years`;
}

/** First view of Documents: what answers can use today, what needs attention, recent changes. */
export function DocOverview({ base, scope, refreshKey, onOpen }: { base: string; scope: string; refreshKey: number; onOpen: (id: string) => void }) {
  const [o, setO] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    // Reloaded on every list refresh: only the latest answer may write, and a success clears an old error.
    let stale = false;
    api<Overview>(`${base}/overview`)
      .then((r) => { if (!stale) { setO(r); setError(null); } })
      .catch((e) => { if (!stale) setError(errorText(e)); });
    return () => { stale = true; };
  }, [base, refreshKey]);

  const types = o ? TYPES.filter(([k]) => o.by_type[k]) : [];
  const check = o ? [o.to_check.low_confidence && `${o.to_check.low_confidence} low OCR`, o.to_check.empty && `${o.to_check.empty} without text`,
    o.to_check.truncated && `${o.to_check.truncated} truncated`].filter(Boolean).join(" · ") : "";
  const q = o?.questions;
  const asked = q ? q.answered + q.not_found + q.errors : 0;

  return (
    <section className="doc-detail doc-overview" aria-label="Overview">
      <header className="doc-head"><h2 className="doc-title">Overview</h2><span className="muted small">{scope} · what answers can use today</span></header>
      <div className="doc-main">
        <div className="ov-body">
          {error && <div className="error" role="alert">{error}</div>}
          {o && <>
            <div className="ov-kpis">
              <div className="ov-kpi"><div className="ov-n">{n(o.in_use)}</div><div className="ov-l">documents in use</div>
                <div className="ov-s">{n(o.documents)} total{o.needs_attention ? ` · ${o.needs_attention} need attention` : ""}</div></div>
              <div className="ov-kpi"><div className="ov-n">{n(o.pages)}</div><div className="ov-l">pages, sections and slides read</div>
                <div className="ov-s">{o.ocr_pages ? `${n(o.ocr_pages)} read with OCR` : "no OCR needed"}</div></div>
              <div className="ov-kpi"><div className="ov-n">{n(o.passages)}</div><div className="ov-l">passages searchable</div>
                <div className="ov-s">{o.embedding_model}</div></div>
              {q ? (
                <div className="ov-kpi"><div className="ov-n">{n(asked)}</div><div className="ov-l">questions in chats on {scope}, 30 days</div>
                  <div className="ov-s">{asked ? `${n(q.not_found)} not found${q.errors ? ` · ${n(q.errors)} errors` : ""}` : "no questions yet"}</div></div>
              ) : (
                <div className="ov-kpi"><div className="ov-n">{n(o.to_check.low_confidence + o.to_check.empty + o.to_check.truncated)}</div><div className="ov-l">pages to check</div>
                  <div className="ov-s">low OCR, without text or truncated</div></div>
              )}
            </div>

            <div className="ov-cols">
              <div className="ov-panel">
                <div className="ov-ph">Needs attention<span>{o.attention.length}</span></div>
                {o.attention.length === 0 && <div className="ov-row muted"><Icon name="check" size={15} />Nothing to do: every document is processed and approved.</div>}
                {o.attention.map((v) => {
                  const s = stateText(v);
                  return (
                    <button key={v.document_id} className="ov-row ov-link" onClick={() => onOpen(v.document_id)}>
                      <span className="ov-nm">{v.document} <span className="muted">v{v.version}</span><span className={`ov-sub ${s.tone}`}>{s.text}</span></span>
                      <span className="ov-act">{v.status === "failed" ? "Retry" : v.approval === "pending" ? "Review" : "Open"}</span>
                    </button>
                  );
                })}
              </div>
              <div className="ov-panel">
                <div className="ov-ph">Content in use</div>
                {o.in_use === 0 ? <div className="ov-row muted">No document in use yet.</div> : <>
                  <div className="ov-bar">{types.map(([k, , c]) => <i key={k} style={{ width: `${(o.by_type[k] / o.in_use) * 100}%`, background: c }} />)}</div>
                  <div className="ov-legend">{types.map(([k, label, c]) => <span key={k}><b style={{ background: c }} />{label} {o.by_type[k]}</span>)}</div>
                </>}
                <dl className="ov-kv">
                  <dt>Last indexed</dt><dd>{o.last_indexed ? <>{o.last_indexed.document} · {dateText(o.last_indexed.processed_at ?? o.last_indexed.uploaded_at)}</> : "—"}</dd>
                  <dt>Oldest in use</dt><dd>{o.oldest_in_use ? <>{o.oldest_in_use.document} · {ago(o.oldest_in_use.uploaded_at)}</> : "—"}</dd>
                  <dt>Pages to check</dt><dd>{check || "none"}</dd>
                </dl>
              </div>
            </div>

            <div className="ov-panel">
              <div className="ov-ph">Recent activity</div>
              {o.recent.length === 0 && <div className="ov-row muted">No uploads yet.</div>}
              {o.recent.map((v) => {
                const s = stateText(v);
                const who = v.reviewed_by && v.approval === "approved" ? `Approved by ${v.reviewed_by}` : v.uploaded_by ? `Uploaded by ${v.uploaded_by}` : "Uploaded";
                return (
                  <button key={`${v.document_id}-${v.version}`} className="ov-row ov-link" onClick={() => onOpen(v.document_id)}>
                    <span className="ov-nm">{v.document} <span className="muted">v{v.version}</span><span className={`ov-sub ${s.tone}`}>{who} · {s.text.toLowerCase()}</span></span>
                    <span className="muted small">{dateText(v.uploaded_at)}</span>
                  </button>
                );
              })}
            </div>
          </>}
        </div>
      </div>
    </section>
  );
}
