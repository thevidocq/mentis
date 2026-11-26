import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ROLE_LABEL } from "../api/types";
import { homePath, useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { Brand } from "../components/Logo";
import { Markdown } from "../components/Markdown";
import { MobileBar } from "../layouts/AdminShell";
import { helpFor } from "../help";

export function Help() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const [drawer, setDrawer] = useState(false); // phones: the topics are in a drawer, like the other menus
  if (!user) return null;

  const groups = helpFor(user.role);
  const all = groups.flatMap((g) => g.topics);
  const current = all.find((t) => t.id === params.get("topic")) ?? all[0];

  return (
    <div className={`shell${drawer ? " drawer-open" : ""}`}>
      <MobileBar title={current?.title ?? "Help"} onMenu={() => setDrawer(true)} />
      <div className="drawer-backdrop" onClick={() => setDrawer(false)} aria-hidden="true" />
      <aside className="sidebar">
        <div className="brand">
          <Brand />
          <button className="icon-btn drawer-close" style={{ border: 0 }} aria-label="Close menu" onClick={() => setDrawer(false)}><Icon name="x" /></button>
        </div>
        <div className="sidebar-block">
          <div className="eyebrow">Help</div>
          <strong>{ROLE_LABEL[user.role]} guide</strong>
        </div>
        <nav className="nav" aria-label="Help topics">
          {groups.map((g) => (
            <div key={g.id} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <div className="eyebrow" style={{ padding: "12px 12px 4px" }}>{g.label}</div>
              {g.topics.map((t) => (
                <a key={t.id} href={`?topic=${t.id}`} className={t.id === current?.id ? "active" : ""}
                  onClick={(e) => { e.preventDefault(); setParams({ topic: t.id }); setDrawer(false); window.scrollTo(0, 0); }}>
                  {t.title}
                </a>
              ))}
            </div>
          ))}
        </nav>
        <Link to={homePath(user)} className="user-link"><Icon name="arrowLeft" />Back to Mentis</Link>
      </aside>
      <main className="main">
        <div className="page-body" style={{ maxWidth: 820 }}>
          {current && <Markdown source={current.body} />}
        </div>
      </main>
    </div>
  );
}
