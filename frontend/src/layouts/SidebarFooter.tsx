import { Link, NavLink, useNavigate } from "react-router-dom";
import { ROLE_LABEL } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";

export function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";
}

/** The account card at the bottom of every sidebar: who is signed in, with Help and Log out at hand. */
export function SidebarFooter() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;
  return (
    <div className="sidebar-footer">
      <div className="account-card">
        <Link to="/account" className="account-who" title="Your account">
          <span className="avatar">{initials(user.full_name)}</span>
          <span className="account-names">
            <span className="account-name">{user.full_name}</span>
            <span className="muted small">{ROLE_LABEL[user.role]}</span>
          </span>
        </Link>
        <NavLink to="/help" className={({ isActive }) => `icon-btn account-action${isActive ? " active" : ""}`} aria-label="Help" title="Help">
          <Icon name="help" size={16} />
        </NavLink>
        <button type="button" className="icon-btn account-action danger" aria-label="Log out" title="Log out"
          onClick={async () => { await logout(); navigate("/login"); }}>
          <Icon name="logout" size={16} />
        </button>
      </div>
      <div className="release-line muted">Mentis {__APP_VERSION__}</div>
    </div>
  );
}
