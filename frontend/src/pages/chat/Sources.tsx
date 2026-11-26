import { useEffect, useMemo, useRef } from "react";
import type { Citation } from "../../api/types";
import { Icon } from "../../components/Icon";

interface Group { key: string; tenant: string; isGeneral: boolean; document: string; version: number; items: Citation[] }

function groupByDocument(citations: Citation[]): Group[] {
  const groups = new Map<string, Group>();
  for (const c of [...citations].sort((a, b) => a.n - b.n)) {
    const key = `${c.tenant}|${c.document}|${c.version}`;
    if (!groups.has(key)) groups.set(key, { key, tenant: c.tenant, isGeneral: c.is_general, document: c.document, version: c.version, items: [] });
    groups.get(key)!.items.push(c);
  }
  return [...groups.values()];
}

const section = (c: Citation) => (c.heading && c.heading !== c.page ? c.heading : c.page);

/**
 * The sources of an answer, compact: one closed line, then one block per document with its
 * cited sections. The customer badge appears only when the answer mixes customers or uses General.
 */
export function Sources({ citations, expanded, onExpand, openN, onOpen }: {
  citations: Citation[]; expanded: boolean; onExpand: (v: boolean) => void; openN: number | null; onOpen: (n: number | null) => void;
}) {
  const groups = useMemo(() => groupByDocument(citations), [citations]);
  const showTenant = new Set(citations.map((c) => c.tenant)).size > 1 || citations.some((c) => c.is_general);
  const ref = useRef<HTMLDivElement>(null);

  // A click on [n] in the text opens the panel on that section.
  useEffect(() => {
    if (openN != null) ref.current?.querySelector(`#src-${openN}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [openN]);

  const docs = groups.length === 1 ? "1 document" : `${groups.length} documents`;
  const parts = citations.length === 1 ? "1 section" : `${citations.length} sections`;
  return (
    <div className="sources" ref={ref}>
      <button type="button" className="sources-toggle" aria-expanded={expanded} onClick={() => { onExpand(!expanded); if (expanded) onOpen(null); }}>
        <Icon name="file" size={14} />
        <span>Sources</span>
        <span className="muted">· {docs} · {parts}</span>
        <span className="spacer" />
        <Icon name={expanded ? "chevronUp" : "chevronDown"} size={14} />
      </button>
      {expanded && groups.map((g) => (
        <div key={g.key} className="source-doc-block">
          <div className="source-doc-name">
            {showTenant && <span className={`pill${g.isGeneral ? "" : " accent"}`}>{g.tenant}</span>}
            <span className="source-doc">{g.document}</span>
            <span className="muted small">v{g.version}</span>
          </div>
          <ul>
            {g.items.map((c) => (
              <li key={c.n} id={`src-${c.n}`} className={openN === c.n ? "open" : ""}>
                <button type="button" className="source-row" aria-expanded={openN === c.n} onClick={() => onOpen(openN === c.n ? null : c.n)}>
                  <span className="cite-n">{c.n}</span>
                  <span className="source-section">{section(c)}</span>
                </button>
                {openN === c.n && <div className="source-text">{c.text}</div>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
