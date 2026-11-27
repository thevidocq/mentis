import { useState } from "react";
import { api, errorText } from "../../api/client";
import type { DocSummary } from "../../api/types";
import { Modal } from "../../components/Modal";

export function RenameModal({ base, doc, onClose, onDone }: { base: string; doc: DocSummary; onClose: () => void; onDone: () => void }) {
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
