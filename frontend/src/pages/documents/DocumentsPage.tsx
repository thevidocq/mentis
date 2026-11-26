import { DragEvent, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, apiUpload, errorText } from "../../api/client";
import type { DocSummary } from "../../api/types";
import { Icon } from "../../components/Icon";
import { DocDetail } from "./DocDetail";
import { DocList } from "./DocList";
import { DocOverview } from "./DocOverview";
import { isBusy } from "./status";
import "./documents.css";

const ACCEPT = ".pdf,.docx,.pptx,.xlsx";

interface Props {
  tenantId: string;
  title: string;
  scopeName?: string;   // the customer's name, for the overview
  previewBase?: string; // kept for the old preview route
  general?: boolean;    // the General Knowledge Base
}

/** Document browser: the list on the left, the selected document on the right. */
export function DocumentsPage({ tenantId, title, scopeName = "this customer", general = false }: Props) {
  const base = `/tenants/${tenantId}/documents`;
  const [docs, setDocs] = useState<DocSummary[] | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [uploads, setUploads] = useState<{ name: string; error?: string; done?: boolean }[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [params, setParams] = useSearchParams();
  const input = useRef<HTMLInputElement>(null);

  // Polling and user actions both reload: only the latest reload may write.
  const seq = useRef(0);
  const load = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const list = await api<DocSummary[]>(base);
      if (mine !== seq.current) return;
      setDocs(list);
      setRefreshKey((k) => k + 1);
      setLoadError(null);
    } catch (e) {
      if (mine === seq.current) setLoadError(errorText(e));
    }
  }, [base]);
  useEffect(() => { void load(); }, [load]);

  const busy = (docs ?? []).some((d) => isBusy(d.latest));
  useEffect(() => {
    if (!busy) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => { timer = setTimeout(() => void load().finally(() => { if (!stop) tick(); }), 3000); };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [busy, load]);

  // An upload leaves the notice once its document has finished processing.
  useEffect(() => {
    const finished = (name: string) => (docs ?? []).some((d) => d.name.toLowerCase() === name.toLowerCase() && !isBusy(d.latest));
    setUploads((u) => (u.some((x) => x.done && finished(x.name)) ? u.filter((x) => !(x.done && finished(x.name))) : u));
  }, [docs]);

  // Selected document: in the address (?doc=); none = the overview.
  const wanted = params.get("doc");
  const doc = docs?.find((d) => d.id === wanted) ?? null;
  const select = (id: string | null) => setParams(id ? { doc: id } : {}, { replace: !id });

  async function upload(files: File[], documentId?: string) {
    setUploads(files.map((f) => ({ name: f.name })));
    let last: string | null = null;
    for (let i = 0; i < files.length; i++) {
      const form = new FormData();
      form.append("file", files[i]);
      if (documentId) form.append("document_id", documentId);
      try {
        const v = await apiUpload<{ id: string }>(base, form);
        last = v.id;
        setUploads((u) => u.map((x, j) => (j === i ? { ...x, done: true } : x)));
      } catch (e) {
        setUploads((u) => u.map((x, j) => (j === i ? { ...x, error: errorText(e) } : x)));
      }
    }
    await load();
    // A single new document: open it.
    if (!documentId && files.length === 1 && last) {
      const list = await api<DocSummary[]>(base).catch(() => null);
      const d = list?.find((x) => x.latest.id === last);
      if (d) select(d.id);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) void upload(Array.from(e.dataTransfer.files));
  }

  return (
    // Phones show the list or the document: a ?doc= that is not (or no longer) in the list keeps the list visible.
    <div className={`docs-browser${wanted && (!docs || doc) ? " has-selection" : ""}`}>
      <aside className="doc-list" aria-label="Documents"
        data-drag={dragging} onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
        <header className="doc-list-head">
          <h1>{title} {docs && <span className="muted">{docs.length}</span>}</h1>
          <button className="btn btn-primary" onClick={() => input.current?.click()}><Icon name="plus" />Upload</button>
          <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => {
            const files = e.target.files ? Array.from(e.target.files) : [];
            e.target.value = "";
            if (files.length) void upload(files);
          }} />
        </header>
        {general && (
          <div className="doc-note" role="note" title="These documents are used in the answers of every customer. Never put customer names, contacts, systems or other customer context here. Every new version needs approval.">
            <Icon name="book" size={14} /><span><strong>General knowledge only</strong>: playbooks and best practices for every customer, never customer context. New versions need approval.</span>
          </div>
        )}
        {uploads.length > 0 && (
          <div className="doc-uploads">
            {uploads.map((u, i) => (
              <div key={i} className="doc-upload">
                <span style={{ color: u.error ? "var(--danger)" : u.done ? "var(--ok)" : "var(--muted)", display: "flex" }}><Icon name={u.error ? "alert" : u.done ? "check" : "clock"} size={14} /></span>
                <span className="doc-upload-name">{u.name}</span>
                <span className={u.error ? "error" : "muted"}>{u.error ?? (u.done ? "processing" : "uploading…")}</span>
              </div>
            ))}
          </div>
        )}
        {loadError && <div className="error doc-error" role="alert">{loadError}</div>}
        <DocList docs={docs ?? []} selected={doc?.id ?? null} onSelect={(id) => select(id)} onOverview={() => select(null)} />
        <div className="doc-drop-hint muted small">Drop files here · PDF, DOCX, PPTX, XLSX · the same file name adds a new version</div>
      </aside>
      {doc ? (
        <DocDetail key={doc.id} base={base} doc={doc} refreshKey={refreshKey} onChanged={() => void load()}
          onDeleted={() => { select(null); void load(); }} onBack={() => select(null)}
          onNewVersion={(f, id) => void upload([f], id)} />
      ) : docs && docs.length > 0 ? (
        <DocOverview base={base} scope={title === "Documents" ? scopeName : title} refreshKey={refreshKey} onOpen={(id) => select(id)} />
      ) : (
        <section className="doc-detail doc-placeholder">
          {docs && docs.length === 0 && (
            <div className="doc-pad doc-notready">
              <Icon name="upload" size={26} />
              <p><strong>Upload the first document</strong><br /><span className="muted">PDF, DOCX, PPTX or XLSX: procedures, escalation matrices, runbooks. Macro-enabled or password-protected files are refused.</span></p>
              <button className="btn btn-primary" onClick={() => input.current?.click()}><Icon name="plus" />Upload</button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
