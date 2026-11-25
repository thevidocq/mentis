import { useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { ROLE_LABEL, type ChatSummary } from "../../api/types";
import { homePath, useAuth } from "../../auth/AuthContext";
import { Icon } from "../../components/Icon";
import { Brand } from "../../components/Logo";
import { Modal } from "../../components/Modal";
import { initials } from "../../layouts/AdminShell";
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
  if (!user) return null;

  return (
    <aside className="sidebar chat-sidebar">
      <div className="brand" style={{ justifyContent: "space-between" }}>
        <Brand />
        <button className="btn btn-sm" onClick={onNew}><Icon name="plus" />New chat</button>
        <button className="icon-btn drawer-close" style={{ border: 0 }} aria-label="Close menu" onClick={onClose}><Icon name="x" /></button>
      </div>
      <div className="sidebar-block">
        <input className="input" type="search" placeholder="Search chats…" aria-label="Search chats" value={query}
          onChange={(e) => onQuery(e.target.value)} style={{ width: "100%" }} />
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
      <Link to="/help" className="user-link" style={{ padding: "10px 16px" }}><Icon name="help" />Help</Link>
      <Link to="/account" className="user-link">
        <div className="avatar">{initials(user.full_name)}</div>
        <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
          <span style={{ fontWeight: 600 }}>{user.full_name}</span>
          <span className="muted small">{ROLE_LABEL[user.role]} · Account</span>
        </div>
        <Icon name="chevronRight" />
      </Link>

      {renaming && (
        <Modal title="Rename chat" onClose={() => setRenaming(null)}
          footer={<>
            <button className="btn" onClick={() => setRenaming(null)}>Cancel</button>
            <button className="btn btn-primary" disabled={!title.trim()} onClick={async () => { await onRename(renaming.id, title.trim()); setRenaming(null); }}>Save</button>
          </>}>
          <label className="field">Title<input className="input" autoFocus maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
          <span className="muted small">A renamed chat keeps its title.</span>
        </Modal>
      )}
      {deleting && (
        <Modal title="Delete chat" danger onClose={() => setDeleting(null)}
          footer={<>
            <button className="btn" onClick={() => setDeleting(null)}>Cancel</button>
            <button className="btn btn-danger" onClick={async () => { await onDelete(deleting.id); setDeleting(null); }}>Delete</button>
          </>}>
          <p style={{ margin: 0 }}>Delete <strong>{deleting.title}</strong> and all its messages? This cannot be undone.</p>
        </Modal>
      )}
    </aside>
  );
}
