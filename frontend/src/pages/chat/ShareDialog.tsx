import { useEffect, useState } from "react";
import { errorText } from "../../api/client";
import type { ShareState } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { chatApi } from "./chatApi";

/** Share a chat by link: read-only, for colleagues signed in to Mentis who see its customer. */
export function ShareDialog({ chatId, onClose, onChange }: { chatId: string; onClose: () => void; onChange: (shared: boolean) => void }) {
  const [state, setState] = useState<ShareState | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { chatApi.shareState(chatId).then(setState).catch((e) => setError(errorText(e))); }, [chatId]);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try { await fn(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  const create = () => run(async () => {
    const s = await chatApi.share(chatId);
    setState(s);
    onChange(true);
    copy(s.url);
  });
  const revoke = () => run(async () => {
    await chatApi.unshare(chatId);
    setState({ url: null, active: false, expires_at: null });
    onChange(false);
  });
  function copy(url: string | null) {
    if (!url) return;
    navigator.clipboard?.writeText(url).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); }).catch(() => undefined);
  }
  const until = state?.expires_at ? new Date(state.expires_at).toLocaleDateString() : null;

  return (
    <Modal title="Share chat" onClose={onClose}
      footer={<>
        {state?.active && <button className="btn btn-danger" disabled={busy} onClick={revoke}>Revoke link</button>}
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={onClose}>Close</button>
        <button className="btn btn-primary" disabled={busy || !state} onClick={create}>
          <Icon name="link" />{state?.active ? "New link" : "Create link"}
        </button>
      </>}>
      <div className="share-dialog">
        <p className="muted" style={{ margin: 0 }}>
          Colleagues signed in to Mentis can read this chat, read-only, if they see its customer.
          Answers that used a customer they do not see stay hidden.
        </p>
        {state?.url ? (
          <div className="share-link">
            <input className="input" readOnly value={state.url} onFocus={(e) => e.currentTarget.select()} aria-label="Share link" />
            <button className="btn" onClick={() => copy(state.url)}><Icon name={copied ? "check" : "copy"} />{copied ? "Copied" : "Copy"}</button>
          </div>
        ) : state?.active ? (
          <p className="small" style={{ margin: 0 }}>
            <span className="pill ok">Link active</span> until {until}. For security the link is shown only when created:
            create a new one to copy it again (the old one stops working).
          </p>
        ) : state ? (
          <p className="small muted" style={{ margin: 0 }}>Not shared.</p>
        ) : null}
        {state?.url && until && <p className="small muted" style={{ margin: 0 }}>Valid until {until}. A new link replaces this one.</p>}
        {error && <div className="answer-error" role="alert"><Icon name="alert" /><div>{error}</div></div>}
      </div>
    </Modal>
  );
}
