import type { DocVersion } from "../../api/types";
import { Icon } from "../../components/Icon";
import { DownloadMenu, type ExportFormat } from "./DownloadMenu";
import { dateText, sizeText, unitText, versionState } from "./status";

export type Action = "approve" | "reject" | "restore" | "retry";

/** Download paths of a version: the original always; Markdown and JSON once it has been read. */
export function versionPaths(base: string, v: DocVersion): Partial<Record<ExportFormat, string>> {
  const read = v.status === "ready";
  return {
    original: `${base}/versions/${v.id}/original`,
    md: read ? `${base}/versions/${v.id}/export?format=md` : undefined,
    json: read ? `${base}/versions/${v.id}/export?format=json` : undefined,
  };
}

/** Every version of the document, newest first, with what can be done on each. */
export function DocVersions({ versions, base, shownId, onAct, onView, onError }: {
  versions: DocVersion[]; base: string; shownId: string; onAct: (v: DocVersion, a: Action) => void;
  onView: (v: DocVersion) => void; onError: (message: string | null) => void;
}) {
  return (
    <div className="doc-pad">
      <div className="doc-versions">
        {versions.map((v) => (
          <VersionRow key={v.id} v={v} base={base} shown={v.id === shownId} onAct={onAct} onError={onError} onView={() => onView(v)} />
        ))}
      </div>
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
