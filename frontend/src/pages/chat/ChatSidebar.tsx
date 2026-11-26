import { useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { errorText } from "../../api/client";
import { type ChatSummary } from "../../api/types";
import { homePath, useAuth } from "../../auth/AuthContext";
import { Icon } from "../../components/Icon";
import { Brand } from "../../components/Logo";
import { Modal } from "../../components/Modal";
import { SidebarFooter } from "../../layouts/SidebarFooter";
import { groupByDay } from "./chatApi";

interface Props {
  chats: ChatSummary[];
  query: string;
  onQuery: (q: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onClose: () => void;
}

export function ChatSidebar({ chats, query, onQuery, onNew, onRename, onDelete, onClose }: Props) {
  const { user } = useAuth();
  const [renaming, setRenaming] = useState<ChatSummary | null>(null);
  const [title, setTitle] = useState("");
  const [deleting, setDeleting] = useState<ChatSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!user) return null;

  // Rename and delete: keep the dialog open with the reason when the server refuses.
  async function run(action: () => Promise<void>, done: () => void) {
    setBusy(true);
    setError(null);
    try { await action(); done(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  const closeRename = () => { setRenaming(null); setError(null); };
  const closeDelete = () => { setDeleting(null); setError(null); };

  return (
    <aside className="sidebar chat-sidebar">
      <div className="brand" style={{ justifyContent: "space-between" }}>
        <Brand />
        <button className="icon-btn drawer-close" style={{ border: 0 }} aria-label="Close menu" onClick={onClose}><Icon name="x" /></button>
      </div>
      <div className="sidebar-block chat-tools">
        <input className="input" type="search" placeholder="Search chats…" aria-label="Search chats" value={query}
          onChange={(e) => onQuery(e.target.value)} />
        <button className="btn new-chat-btn" aria-label="New chat" title="New chat" onClick={onNew}><Icon name="plus" size={18} /></button>
      </div>
      <nav className="nav chat-history" aria-label="Chat history">
        {chats.length === 0 && <span className="muted small" style={{ padding: "8px 10px" }}>{query ? "No chats match." : "No chats yet."}</span>}
        {groupByDay(chats).map((g) => (
          <div key={g.label} className="chat-group">
            <div className="eyebrow" style={{ padding: "10px 12px 4px" }}>{g.label}</div>
            {g.items.map((c) => (
              <div key={c.id} className="chat-item">
                <NavLink to={`/chat/${c.id}`} className={({ isActive }) => (isActive ? "active" : "")} title={c.title}>
                  <span className="chat-item-title">{c.title}</span>
                  <span className="muted small chat-item-scope">{c.scope_name}</span>
                </NavLink>
                <span className="chat-item-actions">
                  <button className="icon-btn" style={{ border: 0 }} aria-label={`Rename ${c.title}`} onClick={() => { setRenaming(c); setTitle(c.title); }}><Icon name="pencil" size={14} /></button>
                  <button className="icon-btn danger" style={{ border: 0 }} aria-label={`Delete ${c.title}`} onClick={() => setDeleting(c)}><Icon name="trash" size={14} /></button>
                </span>
              </div>
            ))}
          </div>
        ))}
      </nav>
      {user.role !== "analyst" && (
        <Link to={homePath(user)} className="user-link" style={{ padding: "10px 16px" }}><Icon name="sliders" />Administration</Link>
      )}
      <SidebarFooter />

      {renaming && (
        <Modal title="Rename chat" onClose={closeRename}
          footer={<>
            <button className="btn" onClick={closeRename}>Cancel</button>
            <button className="btn btn-primary" disabled={busy || !title.trim()} onClick={() => run(() => onRename(renaming.id, title.trim()), closeRename)}>Save</button>
          </>}>
          <label className="field">Title<input className="input" autoFocus maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
          <span className="muted small">A renamed chat keeps its title.</span>
          {error && <div className="error" role="alert">{error}</div>}
        </Modal>
      )}
      {deleting && (
        <Modal title="Delete chat" danger onClose={closeDelete}
          footer={<>
            <button className="btn" onClick={closeDelete}>Cancel</button>
            <button className="btn btn-danger" disabled={busy} onClick={() => run(() => onDelete(deleting.id), closeDelete)}>Delete</button>
          </>}>
          <p style={{ margin: 0 }}>Delete <strong>{deleting.title}</strong> and all its messages? This cannot be undone.</p>
          {error && <div className="error" role="alert">{error}</div>}
        </Modal>
      )}
    </aside>
  );
}
