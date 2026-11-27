import { useEffect, useMemo, useRef, useState } from "react";
import type { Citation } from "../../api/types";
import { Icon } from "../../components/Icon";

interface Group { key: string; tenant: string; isGeneral: boolean; document: string; version: number | null; items: Citation[]; live: Citation | null }

const isLive = (c: Citation) => c.kind === "integration";

function groupByDocument(citations: Citation[]): Group[] {
  const groups = new Map<string, Group>();
  for (const c of [...citations].sort((a, b) => a.n - b.n)) {
    const key = `${c.tenant}|${c.document}|${c.version}`;
    if (!groups.has(key)) groups.set(key, { key, tenant: c.tenant, isGeneral: c.is_general, document: c.document, version: c.version, items: [], live: isLive(c) ? c : null });
    groups.get(key)!.items.push(c);
  }
  return [...groups.values()];
}

const section = (c: Citation) => (c.heading && c.heading !== c.page ? c.heading : c.page);

function summary(citations: Citation[]) {
  const live = citations.filter(isLive).length;
  const docCites = citations.filter((c) => !isLive(c));
  const docs = new Set(docCites.map((c) => `${c.tenant}|${c.document}|${c.version}`)).size;
  const parts = [];
  if (docs) parts.push(`${docs === 1 ? "1 document" : `${docs} documents`} · ${docCites.length === 1 ? "1 section" : `${docCites.length} sections`}`);
  if (live) parts.push(live === 1 ? "1 live record" : `${live} live records`);
  return parts.join(" · ");
}

/** Links of a live record that may be opened: http(s) only (the server already keeps only the product's own). */
export function recordLinks(c: Citation): [string, string][] {
  const out: [string, string][] = [];
  if (c.url) out.push([`Open in ${c.product ?? "the product"}`, c.url]);
  for (const [label, url] of Object.entries(c.links ?? {})) out.push([label, url]);
  return out.filter(([, url]) => /^https?:\/\//i.test(url));
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
export function SourcesPanel({ citations, focus, at = 0, onClose }: { citations: Citation[]; focus: number | null; at?: number; onClose: () => void }) {
  const groups = useMemo(() => groupByDocument(citations), [citations]);
  const showTenant = new Set(citations.map((c) => c.tenant)).size > 1 || citations.some((c) => c.is_general);
  const [open, setOpen] = useState<Set<number>>(new Set(focus != null ? [focus] : citations.length === 1 ? [citations[0].n] : []));
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focus == null) return;
    setOpen((o) => new Set(o).add(focus));
    requestAnimationFrame(() => ref.current?.querySelector(`#src-${focus}`)?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, [focus, citations, at]);

  useEffect(() => {
    // Escape handled elsewhere (the @ customer list) or meant for a dialog on top leaves the panel open.
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape" && !e.defaultPrevented && !document.querySelector('[aria-modal="true"]')) onClose(); };
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
              <Icon name={g.live ? "hash" : "file"} size={14} />
              <span className="source-doc">{g.document}</span>
              {g.live ? <span className="muted small">live · {g.live.integration}</span> : <span className="muted small">v{g.version}</span>}
              {showTenant && <span className={`pill${g.isGeneral ? "" : " accent"}`}>{g.tenant}</span>}
            </div>
            {g.live && recordLinks(g.live).length > 0 && (
              <div className="record-links">
                {recordLinks(g.live).map(([label, url]) => (
                  <a key={url + label} href={url} target="_blank" rel="noopener noreferrer nofollow" className="record-link">
                    <Icon name="external" size={13} />{label}
                  </a>
                ))}
              </div>
            )}
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
