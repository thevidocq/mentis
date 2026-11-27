import { useEffect, useRef, useState } from "react";
import { api, errorText } from "../../api/client";
import type { DocPage, DocSummary, DocVersion } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { DocPages } from "./DocPages";
import { TestQuestion } from "./DocTest";
import { type Action, DocVersions, versionPaths } from "./DocVersions";
import { DownloadMenu } from "./DownloadMenu";
import { LinkPanel } from "./LinkPanel";
import { RenameModal } from "./RenameModal";
import { dateText, sizeText, unitText, versionState } from "./status";

type Tab = "preview" | "text" | "versions" | "test";

// A new version must be the same file type: the picker offers that type and its aliases only.
const ACCEPT_BY_TYPE: Record<string, string> = { md: ".md,.markdown", yaml: ".yaml,.yml", jpg: ".jpg,.jpeg" };
const acceptFor = (fileType: string) => ACCEPT_BY_TYPE[fileType] ?? `.${fileType}`;

interface Props {
  base: string;                // /tenants/{id}/documents
  doc: DocSummary;
  refreshKey: number;          // changes when the list reloaded: versions reload too
  onChanged: () => void;
  onDeleted: () => void;
  onBack: () => void;          // phones: back to the list
  onNewVersion: (file: File, documentId: string) => void;
}

/** The selected document, one column: header (name, state, actions), a facts line, the link it is read
 * from (if any), then Preview, Text read, Versions and Test a question. */
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
  const linked = !!doc.link;
  const warnings = shown.stats?.warnings ?? [];
  const facts = [
    `${shown.file_type.toUpperCase()} · ${sizeText(shown.size_bytes)}`,
    shown.stats?.pages != null ? unitText(shown.file_type, shown.stats.pages) : null,
    ready ? (shown.stats?.ocr_pages ? `text + OCR (${shown.stats.ocr_pages})` : "native text") : null,
    `${linked ? "read" : "uploaded"} ${dateText(shown.uploaded_at)}`,
    shown.note ? `“${shown.note}”` : null,
  ].filter(Boolean) as string[];

  return (
    <section className="doc-detail" aria-label={doc.name}>
      <header className="doc-head">
        <button className="icon-btn doc-back" style={{ border: 0 }} aria-label="Back to documents" onClick={onBack}><Icon name="chevronLeft" /></button>
        <div className="doc-head-text">
          <div className="doc-head-title">
            <h2 className="doc-title">{doc.name}</h2>
            <span className={`doc-status ${st.pill}`}><i />{st.label} · v{shown.version}</span>
            {linked && <span className="doc-chip"><Icon name="link" size={12} />from link</span>}
          </div>
          <div className="doc-facts">{facts.map((f) => <span key={f}>{f}</span>)}</div>
        </div>
        <div className="doc-actions">
          {latest.approval === "pending" && latest.status === "ready" && <>
            <button className="btn btn-primary" onClick={() => act(latest, "approve")}><Icon name="check" />Approve v{latest.version}</button>
            <button className="btn" onClick={() => act(latest, "reject")}>Reject</button>
          </>}
          {latest.status === "failed" && <button className="btn" onClick={() => act(latest, "retry")}><Icon name="refresh" />Retry v{latest.version}</button>}
          <DownloadMenu title={`Download v${shown.version}`} onError={setError} paths={versionPaths(base, shown)}
            unavailable="Available once the version has been read" />
          <div className="menu-wrap">
            <button className="icon-btn" aria-label="More actions" aria-expanded={menu} onClick={(e) => { e.stopPropagation(); setMenu((m) => !m); }}><Icon name="more" /></button>
            {menu && (
              <div className="menu" role="menu">
                {!linked && <button role="menuitem" onClick={() => file.current?.click()}><Icon name="upload" />Upload a new version</button>}
                <button role="menuitem" onClick={() => setRenaming(true)}><Icon name="pencil" />Rename</button>
                <button role="menuitem" onClick={() => setTab("versions")}><Icon name="restore" />Versions and restore</button>
                <button role="menuitem" className="danger" onClick={() => setDeleting(true)}><Icon name="trash" />Delete document</button>
              </div>
            )}
          </div>
          <input ref={file} type="file" accept={acceptFor(latest.file_type)} hidden onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) onNewVersion(f, doc.id);
          }} />
        </div>
      </header>

      {doc.link && <LinkPanel base={base} docId={doc.id} link={doc.link} onChanged={onChanged} />}
      {warnings.map((w) => <div key={w} className="doc-banner warn"><Icon name="alert" size={14} />{w}</div>)}

      <nav className="doc-tabs" role="tablist">
        {([["preview", "Preview"], ["text", "Text read"], ["versions", `Versions (${versions.length || doc.versions})`], ["test", "Test a question"]] as [Tab, string][]).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>
        ))}
        {shown.id !== (doc.active ?? doc.latest).id && (
          <button className="doc-tabs-note" onClick={() => setShownId(null)}>Viewing v{shown.version} · back to the version in use</button>
        )}
      </nav>
      {error && <div className="error doc-error" role="alert">{error}</div>}

      <div className="doc-main">
        {(tab === "preview" || tab === "text") && (
          <DocPages base={base} shown={shown} pages={pages} current={current} onPage={setCurrent} mode={tab} onRetry={() => act(shown, "retry")} />
        )}
        {tab === "versions" && (
          <DocVersions versions={versions} base={base} shownId={shown.id} onAct={act} onError={setError}
            onView={(v) => { setShownId(v.id); setTab("preview"); }} />
        )}
        {tab === "test" && <TestQuestion base={base} version={shown} onOpen={(i) => { setCurrent(i); setTab("preview"); }} />}
      </div>

      {renaming && <RenameModal base={base} doc={doc} onClose={() => setRenaming(false)} onDone={() => { setRenaming(false); onChanged(); }} />}
      {deleting && (
        <Modal danger title={`Delete ${doc.name}?`} onClose={() => setDeleting(false)}
          footer={<><button className="btn" onClick={() => setDeleting(false)}>Cancel</button>
            <button className="btn btn-danger" onClick={async () => {
              try { await api(`${base}/${doc.id}`, { method: "DELETE" }); setDeleting(false); onDeleted(); } catch (e) { setDeleting(false); setError(errorText(e)); }
            }}><Icon name="trash" />Delete document</button></>}>
          <p style={{ margin: 0 }}>All {doc.versions} versions, their extracted text and stored files are deleted. Answers stop using this document.{linked ? " The page is no longer checked." : ""} This cannot be undone.</p>
        </Modal>
      )}
    </section>
  );
}
