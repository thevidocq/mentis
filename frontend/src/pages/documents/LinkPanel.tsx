import { useEffect, useState } from "react";
import { api, errorText } from "../../api/client";
import type { DocLink, LinkCheck } from "../../api/types";
import { Icon } from "../../components/Icon";
import { dateText } from "./status";

export const CHECK_LABEL: Record<LinkCheck, string> = {
  "6h": "Every 6 hours", "1d": "Every day", "7d": "Every week", manual: "Only with Check now",
};

const RESULT: Record<string, string> = { new_version: "changed: new version created", unchanged: "no change" };

/** Where a linked document is read from, how often it is checked, and the last check. */
export function LinkPanel({ base, docId, link, onChanged }: { base: string; docId: string; link: DocLink; onChanged: () => void }) {
  const [busy, setBusy] = useState<"check" | "save" | null>(null);
  const [check, setCheck] = useState<LinkCheck>(link.check); // shown at once, saved in the background
  useEffect(() => setCheck(link.check), [link.check]);
  const [error, setError] = useState<string | null>(null);

  async function call(path: string, method: "POST" | "PATCH", body?: object) {
    setBusy(method === "POST" ? "check" : "save");
    setError(null);
    try {
      await api(`${base}/${docId}/link${path}`, { method, body });
      onChanged();
    } catch (e) {
      setError(errorText(e));
      setCheck(link.check);
    } finally {
      setBusy(null);
    }
  }

  const failed = link.status === "error";
  return (
    <section className={`doc-link${failed ? " failed" : ""}`} aria-label="Read from a link">
      <div className="doc-link-main">
        <span className="doc-link-icon"><Icon name="link" size={16} /></span>
        <div className="doc-link-text">
          <span className="doc-link-label">Read from a link</span>
          <a className="doc-link-url" href={link.url} target="_blank" rel="noopener noreferrer nofollow" title={link.url}>
            <span>{link.url.replace(/^https?:\/\//, "")}</span><Icon name="external" size={12} />
          </a>
        </div>
      </div>
      <div className="doc-link-meta">
        <label className="doc-link-field">
          <span>Check for changes</span>
          <select className="input" value={check} disabled={busy !== null}
            onChange={(e) => { setCheck(e.target.value as LinkCheck); void call("", "PATCH", { check: e.target.value }); }}>
            {(Object.keys(CHECK_LABEL) as LinkCheck[]).map((k) => <option key={k} value={k}>{CHECK_LABEL[k]}</option>)}
          </select>
        </label>
        <div className="doc-link-field">
          <span>Last check</span>
          <strong className={failed ? "fail" : ""}>
            {link.checked_at ? dateText(link.checked_at) : "never"}{link.status && !failed ? ` · ${RESULT[link.status] ?? link.status}` : ""}
          </strong>
        </div>
        {link.next_check_at && !failed && (
          <div className="doc-link-field"><span>Next check</span><strong>{dateText(link.next_check_at)}</strong></div>
        )}
        <button className="btn" disabled={busy !== null} onClick={() => void call("/check", "POST")}>
          <Icon name="refresh" />{busy === "check" ? "Checking…" : "Check now"}
        </button>
      </div>
      {failed && (
        <div className="doc-link-error" role="status">
          <Icon name="alert" size={14} />
          <span><strong>Last check failed.</strong> {(link.error ?? "Unknown error").replace(/\.+$/, "")}. The version in use stays until the page can be read again.</span>
        </div>
      )}
      {error && <div className="error small" role="alert">{error}</div>}
    </section>
  );
}
