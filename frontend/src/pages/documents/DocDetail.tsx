import { FormEvent, useEffect, useRef, useState } from "react";
import { api, errorText } from "../../api/client";
import type { DocPage, DocSummary, DocVersion } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Markdown } from "../../components/Markdown";
import { Modal } from "../../components/Modal";
import { DownloadMenu, type ExportFormat } from "./DownloadMenu";
import { dateText, isBusy, sizeText, unitText, versionState } from "./status";

/** Download paths of a version: the original always; Markdown and JSON once it has been read. */
function versionPaths(base: string, v: DocVersion): Partial<Record<ExportFormat, string>> {
  const read = v.status === "ready";
  return {
    original: `${base}/versions/${v.id}/original`,
    md: read ? `${base}/versions/${v.id}/export?format=md` : undefined,
    json: read ? `${base}/versions/${v.id}/export?format=json` : undefined,
  };
}

type Tab = "preview" | "text" | "versions" | "test";
type Action = "approve" | "reject" | "restore" | "retry";
interface Passage { score: number; page_index: number; page_label: string; heading: string | null; text: string }

const FLAG_LABEL: Record<string, string> = {
  empty: "No text", low_confidence: "Low OCR confidence", merged_cells: "Merged cells", truncated: "Truncated",
};
const ACCEPT = ".pdf,.docx,.pptx,.xlsx,.md,.markdown,.json";

interface Props {
  base: string;                // /tenants/{id}/documents
  doc: DocSummary;
  refreshKey: number;          // changes when the list reloaded: versions reload too
  onChanged: () => void;
  onDeleted: () => void;
  onBack: () => void;          // phones: back to the list
  onNewVersion: (file: File, documentId: string) => void;
}

/** The selected document: actions on top, then Preview, Text read, Versions and Test a question. */
export function DocDetail({ base, doc, refreshKey, onChanged, onDeleted, onBack, onNewVersion }: Props) {
  const [versions, setVersions] = useState<DocVersion[]>([]);
  const [shownId, setShownId] = useState<string | null>(null); // version on screen; default: in use, else latest
  const [pages, setPages] = useState<DocPage[]>([]);
  const [current, setCurrent] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>("preview");
  const [menu, setMenu] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api<{ versions: DocVersion[] }>(`${base}/${doc.id}`).then((d) => setVersions(d.versions)).catch((e) => setError(errorText(e)));
  }, [base, doc.id, refreshKey]);

  const shown = versions.find((v) => v.id === shownId) ?? doc.active ?? doc.latest;
  const ready = shown.status === "ready";
  useEffect(() => {
    setPages([]);
    if (!ready) return;
    // Another version picked meanwhile: its pages, not these, belong on screen.
    let stale = false;
    api<DocPage[]>(`${base}/versions/${shown.id}/pages`).then((p) => {
      if (stale) return;
      setPages(p);
      setCurrent((c) => (p.some((x) => x.index === c) ? c : p[0]?.index ?? null));
    }).catch((e) => { if (!stale) setError(errorText(e)); });
    return () => { stale = true; };
  }, [base, shown.id, ready]);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(false);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [menu]);

  // One action at a time: a double click must not approve (or retry) twice and report a false error.
  const acting = useRef(false);
  async function act(v: DocVersion, action: Action) {
    if (acting.current) return;
    acting.current = true;
    setError(null);
    try {
      await api(`${base}/versions/${v.id}/${action}`, { method: "POST" });
      onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      acting.current = false;
    }
  }

  const st = versionState(shown);
  const latest = doc.latest;
  const pageIdx = pages.findIndex((p) => p.index === current);
  const page = pages[pageIdx] ?? null;

  return (
    <section className="doc-detail" aria-label={doc.name}>
      <header className="doc-head">
        <button className="icon-btn doc-back" style={{ border: 0 }} aria-label="Back to documents" onClick={onBack}><Icon name="chevronLeft" /></button>
        <h2 className="doc-title">{doc.name}</h2>
        <span className={`doc-status ${st.pill}`}><i />{st.label} · v{shown.version}</span>
        <span className="spacer" />
        {latest.approval === "pending" && latest.status === "ready" && <>
          <button className="btn btn-primary" onClick={() => act(latest, "approve")}><Icon name="check" />Approve v{latest.version}</button>
          <button className="btn" onClick={() => act(latest, "reject")}>Reject</button>
        </>}
        {latest.status === "failed" && <button className="btn" onClick={() => act(latest, "retry")}><Icon name="refresh" />Retry v{latest.version}</button>}
        <button className="btn doc-newversion" onClick={() => file.current?.click()}><Icon name="upload" />New version</button>
        <input ref={file} type="file" accept={ACCEPT} hidden onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) onNewVersion(f, doc.id);
        }} />
        <DownloadMenu title={`Download v${shown.version}`} onError={setError} paths={versionPaths(base, shown)}
          unavailable="Available once the version has been read" />
        <div className="menu-wrap">
          <button className="icon-btn" aria-label="More actions" aria-expanded={menu} onClick={(e) => { e.stopPropagation(); setMenu((m) => !m); }}><Icon name="more" /></button>
          {menu && (
            <div className="menu" role="menu">
              <button role="menuitem" onClick={() => setRenaming(true)}><Icon name="pencil" />Rename</button>
              <button role="menuitem" onClick={() => { setTab("versions"); }}><Icon name="restore" />Versions and restore</button>
              <button role="menuitem" className="danger" onClick={() => setDeleting(true)}><Icon name="trash" />Delete document</button>
            </div>
          )}
        </div>
      </header>
      <nav className="doc-tabs" role="tablist">
        {([["preview", "Preview"], ["text", "Text read"], ["versions", `Versions (${versions.length || doc.versions})`], ["test", "Test a question"]] as [Tab, string][]).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>
        ))}
      </nav>
      {error && <div className="error doc-error" role="alert">{error}</div>}

      <div className="doc-body">
        <div className="doc-main">
          {(tab === "preview" || tab === "text") && (
            !ready ? <NotReady v={shown} onRetry={() => act(shown, "retry")} /> : (
              <>
                <div className="doc-pagebar">
                  <button className="icon-btn" style={{ border: 0 }} aria-label="Previous page" disabled={pageIdx <= 0} onClick={() => setCurrent(pages[pageIdx - 1].index)}><Icon name="chevronLeft" /></button>
                  <span>{page ? <>{page.label} <span className="doc-pagecount">{pageIdx + 1} / {pages.length}</span></> : "…"}</span>
                  <button className="icon-btn" style={{ border: 0 }} aria-label="Next page" disabled={pageIdx < 0 || pageIdx >= pages.length - 1} onClick={() => setCurrent(pages[pageIdx + 1].index)}><Icon name="chevronRight" /></button>
                  {page && tab === "text" && <>
                    <span className="doc-pagebar-sep" />
                    <span>{page.method === "ocr" ? `OCR${page.ocr_confidence != null ? ` ${Math.round(page.ocr_confidence * 100)}%` : ""}` : "Native text"}</span>
                    {page.tables > 0 && <span>{page.tables} {page.tables === 1 ? "table" : "tables"}</span>}
                  </>}
                  {page?.flags.map((f) => <span key={f} className="doc-flag"><Icon name="alert" size={13} />{FLAG_LABEL[f] ?? f}</span>)}
                </div>
                <div className="doc-stage">
                  {page && tab === "preview" && page.has_image && (
                    <img className="doc-page-img" src={`/api${base}/versions/${shown.id}/pages/${page.index}/image`} alt={`${page.label} of the original`} />
                  )}
                  {page && (tab === "text" || !page.has_image) && (
                    <article className="doc-page-text">
                      {page.text ? <Markdown source={page.text} breaks /> : <p className="muted" style={{ margin: 0 }}>No text was found on this {page.kind}.</p>}
                    </article>
                  )}
                </div>
              </>
            )
          )}
          {tab === "versions" && (
            <div className="doc-pad">
              <div className="doc-versions">
                {versions.map((v) => (
                  <VersionRow key={v.id} v={v} base={base} shown={v.id === shown.id} onAct={act} onError={setError}
                    onView={() => { setShownId(v.id); setTab("preview"); }} />
                ))}
              </div>
            </div>
          )}
          {tab === "test" && (
            <TestQuestion base={base} version={shown} onOpen={(i) => { setCurrent(i); setTab("preview"); }} />
          )}
        </div>
        <aside className="doc-info" aria-label="Details">
          <div className="doc-info-h">Details</div>
          <dl className="doc-kv">
            <dt>Type</dt><dd>{shown.file_type.toUpperCase()} · {sizeText(shown.size_bytes)}</dd>
            {shown.stats?.pages != null && <><dt>Content</dt><dd>{unitText(shown.file_type, shown.stats.pages)}</dd></>}
            {ready && <><dt>Read with</dt><dd>{shown.stats?.ocr_pages ? `Text + OCR (${shown.stats.ocr_pages})` : "Native text"}</dd></>}
            <dt>Uploaded</dt><dd>{dateText(shown.uploaded_at)}</dd>
            {shown.note && <><dt>Note</dt><dd>{shown.note}</dd></>}
          </dl>
          {(shown.stats?.warnings ?? []).map((w) => <div key={w} className="doc-warn small"><Icon name="alert" size={13} />{w}</div>)}
          <div className="doc-info-h">Versions</div>
          <div className="doc-mini-versions">
            {versions.slice(0, 5).map((v) => {
              const s = versionState(v);
              return (
                <button key={v.id} className={v.id === shown.id ? "on" : ""} onClick={() => setShownId(v.id)}>
                  <span><strong>v{v.version}</strong> <span className="muted">· {new Date(v.uploaded_at).toLocaleDateString()}</span></span>
                  <span className={`doc-mini-state ${s.pill}`}>{s.label}</span>
                </button>
              );
            })}
          </div>
        </aside>
      </div>

      {renaming && <RenameModal base={base} doc={doc} onClose={() => setRenaming(false)} onDone={() => { setRenaming(false); onChanged(); }} />}
      {deleting && (
        <Modal danger title={`Delete ${doc.name}?`} onClose={() => setDeleting(false)}
          footer={<><button className="btn" onClick={() => setDeleting(false)}>Cancel</button>
            <button className="btn btn-danger" onClick={async () => {
              try { await api(`${base}/${doc.id}`, { method: "DELETE" }); setDeleting(false); onDeleted(); } catch (e) { setDeleting(false); setError(errorText(e)); }
            }}><Icon name="trash" />Delete document</button></>}>
          <p style={{ margin: 0 }}>All {doc.versions} versions, their extracted text and stored files are deleted. Answers stop using this document. This cannot be undone.</p>
        </Modal>
      )}
    </section>
  );
}

function NotReady({ v, onRetry }: { v: DocVersion; onRetry: () => void }) {
  return (
    <div className="doc-pad doc-notready">
      {isBusy(v) && <><span className="dots"><i /><i /><i /></span><p>Reading and indexing v{v.version}… The preview appears when it is done.</p></>}
      {v.status === "failed" && <>
        <span style={{ color: "var(--danger)" }}><Icon name="alert" size={22} /></span>
        <p><strong>Processing of v{v.version} failed.</strong><br /><span className="muted">{v.error ?? "Unknown error."}</span></p>
        <button className="btn" onClick={onRetry}><Icon name="refresh" />Retry</button>
      </>}
    </div>
  );
}

function VersionRow({ v, base, shown, onAct, onView, onError }: {
  v: DocVersion; base: string; shown: boolean; onAct: (v: DocVersion, a: Action) => void; onView: () => void; onError: (message: string | null) => void;
}) {
  const st = versionState(v);
  const canRestore = v.status === "ready" && !v.is_active && (v.approval === "not_required" || v.approval === "approved");
  return (
    <div className={`doc-version${shown ? " on" : ""}`}>
      <strong className="doc-version-n">v{v.version}</strong>
      <span className={`doc-mini-state ${st.pill}`}>{st.label}</span>
      <span className="muted small doc-version-meta">
        {dateText(v.uploaded_at)} · {sizeText(v.size_bytes)}{v.stats?.pages ? ` · ${unitText(v.file_type, v.stats.pages)}` : ""}
        {v.note && <> · “{v.note}”</>}
        {v.error && <span className="error"> · {v.error}</span>}
      </span>
      <span className="spacer row" style={{ gap: 6 }}>
        {v.status === "ready" && !shown && <button className="btn btn-sm" onClick={onView}><Icon name="eye" />View</button>}
        {v.approval === "pending" && v.status === "ready" && <>
          <button className="btn btn-sm btn-primary" onClick={() => onAct(v, "approve")}>Approve</button>
          <button className="btn btn-sm" onClick={() => onAct(v, "reject")}>Reject</button>
        </>}
        {canRestore && <button className="btn btn-sm" onClick={() => onAct(v, "restore")}><Icon name="restore" />Make active</button>}
        {v.status === "failed" && <button className="btn btn-sm" onClick={() => onAct(v, "retry")}><Icon name="refresh" />Retry</button>}
        <DownloadMenu title={`Download v${v.version}`} onError={onError} paths={versionPaths(base, v)}
          unavailable="Available once the version has been read" />
      </span>
    </div>
  );
}

function TestQuestion({ base, version, onOpen }: { base: string; version: DocVersion; onOpen: (pageIndex: number) => void }) {
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

function RenameModal({ base, doc, onClose, onDone }: { base: string; doc: DocSummary; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState(doc.name);
  const [error, setError] = useState<string | null>(null);
  async function save() {
    try {
      await api(`${base}/${doc.id}`, { method: "PATCH", body: { name } });
      onDone();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <Modal title="Rename document" onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={save} disabled={!name.trim()}>Save</button></>}>
      <label className="field">Name<input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus /></label>
      <span className="muted small">New uploads with this name become new versions of this document.</span>
      {error && <div className="error" role="alert">{error}</div>}
    </Modal>
  );
}
