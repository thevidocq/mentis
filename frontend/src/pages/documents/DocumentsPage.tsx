import { DragEvent, Fragment, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, apiUpload, errorText } from "../../api/client";
import type { DocSummary, DocVersion } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { PageHead } from "../../layouts/AdminShell";
import { dateText, isBusy, sizeText, unitText, versionState } from "./status";

const ACCEPT = ".pdf,.docx,.pptx,.xlsx";

interface Props {
  tenantId: string;
  title: string;
  previewBase: string; // e.g. "/tenant/documents/preview"
}

export function DocumentsPage({ tenantId, title, previewBase }: Props) {
  const base = `/tenants/${tenantId}/documents`;
  const [docs, setDocs] = useState<DocSummary[]>([]);
  const [open, setOpen] = useState<Record<string, DocVersion[]>>({});
  const [uploads, setUploads] = useState<{ name: string; error?: string; done?: boolean }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [renaming, setRenaming] = useState<DocSummary | null>(null);
  const [deleting, setDeleting] = useState<DocSummary | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const list = await api<DocSummary[]>(base);
      setDocs(list);
      // Refresh expanded version lists too.
      const ids = Object.keys(open);
      if (ids.length) {
        const entries = await Promise.all(ids.map(async (id) => [id, (await api<{ versions: DocVersion[] }>(`${base}/${id}`).catch(() => ({ versions: [] }))).versions] as const));
        setOpen(Object.fromEntries(entries));
      }
    } catch (e) {
      setError(errorText(e));
    }
  }, [base, open]);

  useEffect(() => { void load(); }, [tenantId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll while something is being processed.
  const busy = docs.some((d) => isBusy(d.latest));
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => void load(), 3000);
    return () => clearInterval(id);
  }, [busy, load]);

  async function uploadFiles(files: FileList | File[]) {
    const list = Array.from(files);
    setUploads(list.map((f) => ({ name: f.name })));
    for (let i = 0; i < list.length; i++) {
      const form = new FormData();
      form.append("file", list[i]);
      try {
        await apiUpload(base, form);
        setUploads((u) => u.map((x, j) => (j === i ? { ...x, done: true } : x)));
      } catch (e) {
        setUploads((u) => u.map((x, j) => (j === i ? { ...x, error: errorText(e) } : x)));
      }
    }
    await load();
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) void uploadFiles(e.dataTransfer.files);
  }

  async function toggle(doc: DocSummary) {
    if (open[doc.id]) {
      const { [doc.id]: _, ...rest } = open;
      setOpen(rest);
      return;
    }
    const detail = await api<{ versions: DocVersion[] }>(`${base}/${doc.id}`);
    setOpen({ ...open, [doc.id]: detail.versions });
  }

  async function act(v: DocVersion, action: "approve" | "reject" | "restore" | "retry") {
    try {
      await api(`${base}/versions/${v.id}/${action}`, { method: "POST" });
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  }

  const ready = docs.filter((d) => d.active).length;

  return (
    <>
      <PageHead title={title}>
        <span className="muted">{docs.length} {docs.length === 1 ? "document" : "documents"} · {ready} in use</span>
        <button className="btn btn-primary spacer" onClick={() => input.current?.click()}><Icon name="upload" />Upload documents</button>
        <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => e.target.files && void uploadFiles(e.target.files)} />
      </PageHead>
      <div className="page-body">
        <div
          className="dropzone"
          data-active={dragging}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <Icon name="upload" size={22} />
          <strong>Drop files here</strong>
          <span className="muted small">PDF, DOCX, PPTX, XLSX · the same file name adds a new version · macro-enabled or password-protected files are refused</span>
        </div>

        {uploads.length > 0 && (
          <div className="notice stack" style={{ gap: 4 }}>
            {uploads.map((u, i) => (
              <div key={i} className="row small" style={{ gap: 8 }}>
                <span style={{ color: u.error ? "var(--danger)" : u.done ? "var(--ok)" : "var(--muted)", display: "flex" }}>
                  <Icon name={u.error ? "alert" : u.done ? "check" : "clock"} />
                </span>
                <strong>{u.name}</strong>
                <span className={u.error ? "error" : "muted"}>{u.error ?? (u.done ? "uploaded, processing" : "uploading…")}</span>
              </div>
            ))}
          </div>
        )}
        {error && <div className="error" role="alert">{error}</div>}

        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Document</th><th>Type</th><th>In use</th><th>Latest</th><th>Updated</th><th style={{ textAlign: "right" }}>Actions</th></tr>
            </thead>
            <tbody>
              {docs.length === 0 && (
                <tr><td colSpan={6} className="muted">No documents yet. Upload procedures, escalation matrices and runbooks.</td></tr>
              )}
              {docs.map((d) => {
                const latest = versionState(d.latest);
                const versions = open[d.id];
                return (
                  <Fragment key={d.id}>
                    <tr>
                      <td><strong>{d.name}</strong></td>
                      <td className="muted">{d.latest.file_type.toUpperCase()}</td>
                      <td>{d.active ? `v${d.active.version}` : <span className="muted">none</span>}</td>
                      <td><span className={`pill ${latest.pill}`}>v{d.latest.version} · {latest.label}</span></td>
                      <td className="muted">{dateText(d.latest.uploaded_at)}</td>
                      <td>
                        <div className="actions">
                          <button className="btn btn-sm" aria-expanded={!!versions} onClick={() => void toggle(d)}>
                            Versions ({d.versions}) <Icon name={versions ? "chevronDown" : "chevronRight"} size={14} />
                          </button>
                          <Link className="icon-btn" aria-label={`Preview ${d.name}`} title="Preview" to={`${previewBase}/${d.latest.id}`}><Icon name="eye" /></Link>
                          <button className="icon-btn" aria-label={`Rename ${d.name}`} onClick={() => setRenaming(d)}><Icon name="pencil" /></button>
                          <button className="icon-btn danger" aria-label={`Delete ${d.name}`} onClick={() => setDeleting(d)}><Icon name="trash" /></button>
                        </div>
                      </td>
                    </tr>
                    {versions && (
                      <tr>
                        <td colSpan={6} style={{ background: "var(--surface-2)", padding: "8px 16px 12px 32px" }}>
                          <div className="stack" style={{ gap: 6, borderLeft: "2px solid var(--border)", paddingLeft: 14 }}>
                            {versions.map((v) => <VersionRow key={v.id} v={v} previewBase={previewBase} base={base} onAct={act} />)}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {renaming && <RenameModal base={base} doc={renaming} onClose={() => setRenaming(null)} onDone={() => { setRenaming(null); void load(); }} />}
      {deleting && (
        <Modal danger title={`Delete ${deleting.name}?`} onClose={() => setDeleting(null)}
          footer={<><button className="btn" onClick={() => setDeleting(null)}>Cancel</button>
            <button className="btn btn-danger" onClick={async () => {
              try { await api(`${base}/${deleting.id}`, { method: "DELETE" }); } catch (e) { setError(errorText(e)); }
              setDeleting(null); void load();
            }}><Icon name="trash" />Delete document</button></>}>
          <p style={{ margin: 0 }}>All {deleting.versions} versions, their extracted text and stored files are deleted. Answers stop using this document. This cannot be undone.</p>
        </Modal>
      )}
    </>
  );
}

function VersionRow({ v, previewBase, base, onAct }: {
  v: DocVersion; previewBase: string; base: string; onAct: (v: DocVersion, a: "approve" | "reject" | "restore" | "retry") => void;
}) {
  const st = versionState(v);
  const canRestore = v.status === "ready" && !v.is_active && (v.approval === "not_required" || v.approval === "approved");
  return (
    <div className="row small" style={{ gap: 10 }}>
      <strong style={{ minWidth: 30 }}>v{v.version}</strong>
      <span className={`pill ${st.pill}`}>{st.label}</span>
      <span className="muted">{dateText(v.uploaded_at)} · {sizeText(v.size_bytes)}{v.stats?.pages ? ` · ${unitText(v.file_type, v.stats.pages)}` : ""}{v.stats?.ocr_pages ? ` · ${v.stats.ocr_pages} OCR` : ""}</span>
      {v.note && <span className="muted">“{v.note}”</span>}
      {v.error && <span className="error">{v.error}</span>}
      <span className="spacer row" style={{ gap: 6 }}>
        {v.status === "ready" && <Link className="btn btn-sm" to={`${previewBase}/${v.id}`}><Icon name="eye" />Preview</Link>}
        {v.approval === "pending" && v.status === "ready" && <>
          <button className="btn btn-sm btn-primary" onClick={() => onAct(v, "approve")}>Approve</button>
          <button className="btn btn-sm" onClick={() => onAct(v, "reject")}>Reject</button>
        </>}
        {canRestore && <button className="btn btn-sm" onClick={() => onAct(v, "restore")}><Icon name="restore" />Make active</button>}
        {v.status === "failed" && <button className="btn btn-sm" onClick={() => onAct(v, "retry")}><Icon name="refresh" />Retry</button>}
        <a className="icon-btn" aria-label={`Download v${v.version}`} title="Download original" href={`/api${base}/versions/${v.id}/original`}><Icon name="download" /></a>
      </span>
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
