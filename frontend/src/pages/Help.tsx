import { Link, useSearchParams } from "react-router-dom";
import { ROLE_LABEL } from "../api/types";
import { homePath, useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { Brand } from "../components/Logo";
import { Markdown } from "../components/Markdown";
import { helpFor } from "../help";

export function Help() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  if (!user) return null;

  const groups = helpFor(user.role);
  const all = groups.flatMap((g) => g.topics);
  const current = all.find((t) => t.id === params.get("topic")) ?? all[0];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><Brand /></div>
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
                  onClick={(e) => { e.preventDefault(); setParams({ topic: t.id }); window.scrollTo(0, 0); }}>
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
