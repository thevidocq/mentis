import { Link } from "react-router-dom";
import { ROLE_LABEL } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { Brand } from "../components/Logo";
import { initials } from "../layouts/AdminShell";

// Chat shell. Conversations, @ customer scope and answers arrive with the chat block.
export function ChatHome() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <div className="shell">
      <aside className="sidebar" style={{ flexBasis: 280 }}>
        <div className="brand" style={{ justifyContent: "space-between" }}>
          <Brand />
          <button className="btn btn-sm" disabled><Icon name="plus" />New chat</button>
        </div>
        <div className="sidebar-block">
          <label className="field">Search history<input className="input" type="search" placeholder="Search chats…" disabled /></label>
        </div>
        <nav className="nav" aria-label="Chat history"><span className="muted small" style={{ padding: "8px 10px" }}>No chats yet.</span></nav>
        <Link to="/help" className="user-link" style={{ padding: "10px 16px" }}><Icon name="help" />Help</Link>
        <Link to="/account" className="user-link">
          <div className="avatar">{initials(user.full_name)}</div>
          <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
            <span style={{ fontWeight: 600 }}>{user.full_name}</span>
            <span className="muted small">{ROLE_LABEL[user.role]} · Account</span>
          </div>
          <Icon name="chevronRight" />
        </Link>
      </aside>
      <main className="main" style={{ alignItems: "center", justifyContent: "center", padding: 32 }}>
        <div className="stack" style={{ maxWidth: 520, textAlign: "center", alignItems: "center" }}>
          <span style={{ color: "var(--accent-text)" }}><Icon name="chat" size={40} /></span>
          <h1>Chat is coming</h1>
          <p className="muted" style={{ margin: 0 }}>
            Your account is ready. Answers from customer documentation, the <strong>@</strong> customer selector and
            <strong> #</strong> integrations arrive once document ingestion is in place.
          </p>
        </div>
      </main>
    </div>
  );
}
