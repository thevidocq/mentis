import { useEffect, useMemo, useRef, useState } from "react";
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

function summary(citations: Citation[]) {
  const docs = new Set(citations.map((c) => `${c.tenant}|${c.document}|${c.version}`)).size;
  return `${docs === 1 ? "1 document" : `${docs} documents`} · ${citations.length === 1 ? "1 section" : `${citations.length} sections`}`;
}

/** The closed line under an answer: opens the sources panel on the right. */
export function SourcesBar({ citations, active, onOpen }: { citations: Citation[]; active: boolean; onOpen: () => void }) {
  return (
    <button type="button" className={`sources-toggle${active ? " active" : ""}`} aria-expanded={active} onClick={onOpen}>
      <Icon name="file" size={14} />
      <span>Sources</span>
      <span className="muted">· {summary(citations)}</span>
      <span className="spacer" />
      <Icon name="chevronRight" size={14} />
    </button>
  );
}

/**
 * Sources of one answer in a side panel (like a reference viewer): one block per document with its
 * cited sections; the section picked with [n] is open and in view. The customer badge appears only
 * when the answer mixes customers or uses the General Knowledge Base.
 */
export function SourcesPanel({ citations, focus, onClose }: { citations: Citation[]; focus: number | null; onClose: () => void }) {
  const groups = useMemo(() => groupByDocument(citations), [citations]);
  const showTenant = new Set(citations.map((c) => c.tenant)).size > 1 || citations.some((c) => c.is_general);
  const [open, setOpen] = useState<Set<number>>(new Set(focus != null ? [focus] : citations.length === 1 ? [citations[0].n] : []));
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focus == null) return;
    setOpen((o) => new Set(o).add(focus));
    requestAnimationFrame(() => ref.current?.querySelector(`#src-${focus}`)?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, [focus, citations]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [onClose]);

  const toggle = (n: number) => setOpen((o) => { const s = new Set(o); if (s.has(n)) s.delete(n); else s.add(n); return s; });
  return (
    <aside className="sources-panel" aria-label="Sources">
      <header className="sources-panel-head">
        <strong>Sources</strong>
        <span className="muted small">{summary(citations)}</span>
        <span className="spacer" />
        <button type="button" className="icon-btn" style={{ border: 0 }} aria-label="Close sources" onClick={onClose}><Icon name="x" /></button>
      </header>
      <div className="sources-panel-body" ref={ref}>
        {groups.map((g) => (
          <section key={g.key} className="source-doc-block">
            <div className="source-doc-name">
              <Icon name="file" size={14} />
              <span className="source-doc">{g.document}</span>
              <span className="muted small">v{g.version}</span>
              {showTenant && <span className={`pill${g.isGeneral ? "" : " accent"}`}>{g.tenant}</span>}
            </div>
            <ul>
              {g.items.map((c) => (
                <li key={c.n} id={`src-${c.n}`} className={open.has(c.n) ? "open" : ""}>
                  <button type="button" className="source-row" aria-expanded={open.has(c.n)} onClick={() => toggle(c.n)}>
                    <span className="cite-n">{c.n}</span>
                    <span className="source-section">{section(c)}</span>
                    <Icon name={open.has(c.n) ? "chevronUp" : "chevronDown"} size={14} />
                  </button>
                  {open.has(c.n) && <div className="source-text">{c.text}</div>}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </aside>
  );
}
