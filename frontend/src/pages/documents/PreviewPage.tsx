import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorText } from "../../api/client";
import type { DocPage, DocVersion } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Markdown } from "../../components/Markdown";
import { PageHead } from "../../layouts/AdminShell";
import { unitText, versionState } from "./status";

interface Passage { score: number; page_index: number; page_label: string; heading: string | null; text: string }

const FLAG_LABEL: Record<string, string> = {
  empty: "No text",
  low_confidence: "Low OCR confidence",
  merged_cells: "Merged cells",
  truncated: "Truncated",
};

/** Side-by-side check of what Mentis extracted from a version. */
export function PreviewPage({ tenantId, backTo }: { tenantId: string; backTo: string }) {
  const { versionId = "" } = useParams();
  const base = `/tenants/${tenantId}/documents/versions/${versionId}`;
  const [version, setVersion] = useState<DocVersion | null>(null);
  const [pages, setPages] = useState<DocPage[]>([]);
  const [current, setCurrent] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [passages, setPassages] = useState<Passage[] | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  async function ask(e: FormEvent) {
    e.preventDefault();
    setAsking(true);
    setAskError(null);
    try {
      setPassages(await api<Passage[]>(`${base}/search`, { method: "POST", body: { question } }));
    } catch (err) {
      setAskError(errorText(err));
      setPassages(null);
    } finally {
      setAsking(false);
    }
  }

  const load = () => {
    api<DocVersion>(base).then(setVersion).catch((e) => setError(errorText(e)));
    api<DocPage[]>(`${base}/pages`).then(setPages).catch((e) => setError(errorText(e)));
  };
  useEffect(load, [base]); // eslint-disable-line react-hooks/exhaustive-deps

  async function act(action: "approve" | "reject") {
    try {
      setVersion(await api<DocVersion>(`${base}/${action}`, { method: "POST" }));
    } catch (e) {
      setError(errorText(e));
    }
  }

  const page = pages.find((p) => p.index === current) ?? pages[0];
  const st = version ? versionState(version) : null;
  const s = version?.stats ?? {};
  const flagged = pages.filter((p) => p.flags.length > 0).length;

  return (
    <>
      <PageHead title={version ? `${version.original_filename} · v${version.version}` : "Preview"}>
        {st && <span className={`pill ${st.pill}`}>{st.label}</span>}
        <span className="spacer row" style={{ gap: 8 }}>
          {version?.approval === "pending" && version.status === "ready" && <>
            <button className="btn btn-primary" onClick={() => act("approve")}><Icon name="check" />Approve and publish</button>
            <button className="btn" onClick={() => act("reject")}>Reject</button>
          </>}
          {version && <a className="btn" href={`/api${base}/original`}><Icon name="download" />Original</a>}
          <Link className="btn" to={backTo}><Icon name="arrowLeft" />Documents</Link>
        </span>
      </PageHead>
      <div className="page-body">
        {error && <div className="error" role="alert">{error}</div>}
        {version && (
          <div className="row small muted" style={{ gap: 16 }}>
            <span>{unitText(version.file_type, s.pages ?? 0)}</span>
            <span>{s.ocr_pages ?? 0} read with OCR</span>
            <span>{s.tables ?? 0} {s.tables === 1 ? "table" : "tables"}</span>
            <span style={{ color: flagged ? "var(--warn)" : undefined }}>{flagged} to check</span>
            {(s.warnings ?? []).map((w) => <span key={w} style={{ color: "var(--warn)" }}>{w}</span>)}
          </div>
        )}
        {version?.status === "ready" && (
          <section className="card">
            <form className="card-head row" onSubmit={ask} style={{ gap: 10 }}>
              <h2>Test a question</h2>
              <input className="input" style={{ flex: 1, minWidth: 240 }} value={question} onChange={(e) => setQuestion(e.target.value)}
                placeholder="e.g. Who is the on-call contact for high severity?" aria-label="Question to test" />
              <button className="btn btn-primary" disabled={asking || question.trim().length < 2}>Find passages</button>
            </form>
            {(passages || askError) && (
              <div className="card-body stack" style={{ gap: 10 }}>
                {askError && <div className="error" role="alert">{askError}</div>}
                {passages && passages.length === 0 && <span className="muted">No passage of this version matches. Answers would say "not found".</span>}
                {passages?.map((p, i) => (
                  <div key={i} className="notice stack" style={{ gap: 6 }}>
                    <div className="row small" style={{ gap: 8 }}>
                      <button className="btn btn-sm" onClick={() => setCurrent(p.page_index)}>{p.page_label}</button>
                      {p.heading && <strong>{p.heading}</strong>}
                      <span className="spacer muted">match {Math.round(p.score * 100)}%</span>
                    </div>
                    <Markdown source={p.text} breaks />
                  </div>
                ))}
                {passages && passages.length > 0 && <span className="muted small">These are the passages Mentis would use to answer. The chat will turn them into an answer with citations.</span>}
              </div>
            )}
          </section>
        )}
        <div className="preview">
          <nav className="preview-pages" aria-label="Pages">
            {pages.map((p) => (
              <button key={p.index} className={p.index === page?.index ? "active" : ""} onClick={() => setCurrent(p.index)}>
                <span>{p.label}</span>
                {p.flags.length > 0 && <span style={{ color: "var(--warn)", display: "flex" }} title={p.flags.map((f) => FLAG_LABEL[f] ?? f).join(", ")}><Icon name="alert" size={14} /></span>}
              </button>
            ))}
          </nav>
          {page && (
            <div className="preview-body">
              <section className="card preview-pane">
                <div className="card-head"><h2>Original</h2></div>
                <div className="card-body">
                  {page.has_image
                    ? <img src={`/api${base}/pages/${page.index}/image`} alt={`${page.label} of the original`} style={{ width: "100%", border: "1px solid var(--border)", borderRadius: 6, background: "#fff" }} />
                    : <p className="muted" style={{ margin: 0 }}>No page image for {version?.file_type.toUpperCase()} files. Open the <a href={`/api${base}/original`}>original</a> to compare.</p>}
                </div>
              </section>
              <section className="card preview-pane">
                <div className="card-head">
                  <h2 style={{ flex: 1 }}>What Mentis read</h2>
                  <span className={`pill ${page.method === "ocr" ? "warn" : ""}`}>
                    {page.method === "ocr" ? `OCR ${page.ocr_confidence != null ? Math.round(page.ocr_confidence * 100) + "%" : ""}` : "Native text"}
                  </span>
                  {page.ocr_confidence != null && page.method !== "ocr" && <span className="pill">Image text {Math.round(page.ocr_confidence * 100)}%</span>}
                  {page.tables > 0 && <span className="pill">{page.tables} {page.tables === 1 ? "table" : "tables"}</span>}
                  {page.flags.map((f) => <span key={f} className="pill warn">{FLAG_LABEL[f] ?? f}</span>)}
                </div>
                <div className="card-body">
                  {page.text ? <Markdown source={page.text} breaks /> : <p className="muted" style={{ margin: 0 }}>No text was found on this page.</p>}
                </div>
              </section>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
