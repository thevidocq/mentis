import { FormEvent, useState } from "react";
import { api, errorText } from "../../api/client";
import type { LinkCheck } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { CHECK_LABEL } from "./LinkPanel";

/** Add documentation from a public link: read now, then checked for changes on its schedule. */
export function AddLinkDialog({ base, onClose, onAdded }: { base: string; onClose: () => void; onAdded: (versionId: string) => void }) {
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [check, setCheck] = useState<LinkCheck>("1d");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function add(e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const v = await api<{ id: string }>(`${base}/link`, { method: "POST", body: { url: url.trim(), name: name.trim() || null, check } });
      onAdded(v.id);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Add documentation from a link" onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !/^https?:\/\/\S+$/i.test(url.trim())} onClick={() => void add()}>
          <Icon name="link" />{busy ? "Reading the page…" : "Add"}
        </button>
      </>}>
      <form className="stack" style={{ gap: 14 }} onSubmit={add}>
        <label className="field">Address
          <input className="input mono" type="url" value={url} autoFocus placeholder="https://github.com/acme/runbooks/blob/main/apache.md"
            onChange={(e) => setUrl(e.target.value)} />
          <span className="muted small">A public page or file: web page, Markdown or text, PDF, JSON, YAML, CSV. A GitHub file link is read from its raw version. Pages that need a sign-in or JavaScript cannot be read.</span>
        </label>
        <div className="row" style={{ gap: 12, alignItems: "flex-start" }}>
          <label className="field" style={{ flex: 1 }}>Name <span className="muted">(optional)</span>
            <input className="input" value={name} maxLength={200} placeholder="From the page" onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field" style={{ flex: 1 }}>Check for changes
            <select className="input" value={check} onChange={(e) => setCheck(e.target.value as LinkCheck)}>
              {(Object.keys(CHECK_LABEL) as LinkCheck[]).map((k) => <option key={k} value={k}>{CHECK_LABEL[k]}</option>)}
            </select>
          </label>
        </div>
        <span className="muted small">When the page changes, Mentis creates a new version, approved like an upload if this customer requires approval. When it cannot be read, the version in use stays.</span>
        {error && <div className="error" role="alert">{error}</div>}
      </form>
    </Modal>
  );
}
