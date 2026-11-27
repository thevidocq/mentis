// Minimal Markdown renderer for the help pages: builds React elements, never injects HTML.
// Supports: # ## ### headings, paragraphs, - and 1. lists (one nested level, 4 spaces),
// > notes, ``` code blocks, | tables |, **bold**, *italic* and `code` inline.
// With `cite`, [n] markers in chat answers become citation links. With `marks`, those exact
// passages of the source are highlighted (answer check findings). With `links`, [text](url) becomes
// a link only when url is one of them (the pages of live records); any other address stays text.

import { ReactNode } from "react";

type Cite = (n: number, key: string) => ReactNode;

const OPEN = "\uE000";        // a finding: not in the sources
const CLOSE = "\uE001";
const OPEN_SOFT = "\uE002";   // a note: a statement without a citation
const CLOSE_SOFT = "\uE003";
const MARKERS = /([\uE000-\uE003])/;

export type Mark = string | { text: string; soft?: boolean };

/** Text with highlight markers -> nodes; `state.cls` carries a highlight across bold or code. */
function marked(text: string, key: string, state: { cls: string | null }): ReactNode[] {
  if (!MARKERS.test(text)) return [state.cls ? <mark key={key} className={state.cls}>{text}</mark> : text];
  const out: ReactNode[] = [];
  text.split(MARKERS).forEach((part, i) => {
    if (part === OPEN) state.cls = "check-mark";
    else if (part === OPEN_SOFT) state.cls = "check-mark soft";
    else if (part === CLOSE || part === CLOSE_SOFT) state.cls = null;
    else if (part) out.push(state.cls ? <mark key={`${key}m${i}`} className={state.cls}>{part}</mark> : part);
  });
  return out;
}

const opens = (s: string) => (s.match(/[\uE000\uE002]/g) ?? []).length;
const closes = (s: string) => (s.match(/[\uE001\uE003]/g) ?? []).length;

/** Insert highlight markers around the first occurrence of each mark (longest first). */
function withMarks(source: string, marks: Mark[]): string {
  let s = source;
  const all = marks.map((m) => (typeof m === "string" ? { text: m, soft: false } : { text: m.text, soft: !!m.soft }))
    .filter((m) => m.text && m.text.trim().length > 1)
    .sort((a, b) => Number(a.soft) - Number(b.soft) || b.text.length - a.text.length); // findings first
  const seen = new Set<string>();
  for (const m of all) {
    if (seen.has(m.text)) continue;
    seen.add(m.text);
    const at = s.indexOf(m.text);
    if (at < 0 || opens(s.slice(0, at)) !== closes(s.slice(0, at))) continue; // not found, or inside another
    if (MARKERS.test(s.slice(at, at + m.text.length))) continue;
    s = s.slice(0, at) + (m.soft ? OPEN_SOFT : OPEN) + m.text + (m.soft ? CLOSE_SOFT : CLOSE) + s.slice(at + m.text.length);
  }
  return s;
}

const LINK = /^\[([^\]\n]{1,300})\]\((https?:\/\/[^\s)]{1,1000})\)$/;

function inline(text: string, cite?: Cite, links?: Set<string>): ReactNode[] {
  const state: { cls: string | null } = { cls: null };
  const out: ReactNode[] = [];
  const link = "\\[[^\\]\\n]{1,300}\\]\\(https?:\\/\\/[^\\s)]{1,1000}\\)|";
  const re = new RegExp(`(${links ? link : ""}\\*\\*[^*]+\\*\\*|\`[^\`]+\`|\\*[^*\\s][^*]*\\*${cite ? "|\\[\\d{1,3}\\]" : ""})`, "g");
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(...marked(text.slice(last, m.index), `t${last}`, state));
    const tok = m[0];
    const k = `${m.index}`;
    const l = links && tok.startsWith("[") ? LINK.exec(tok) : null;
    if (l) {
      out.push(links!.has(l[2])
        ? <a key={k} href={l[2]} target="_blank" rel="noopener noreferrer nofollow" className="record-inline-link">{marked(l[1], k, state)}</a>
        : <span key={k}>{marked(l[1], k, state)}</span>);
    } else if (tok.startsWith("**")) out.push(<strong key={k}>{marked(tok.slice(2, -2), k, state)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={k}>{marked(tok.slice(1, -1), k, state)}</code>);
    else if (tok.startsWith("[") && cite) out.push(cite(Number(tok.slice(1, -1)), k));
    else out.push(<em key={k}>{marked(tok.slice(1, -1), k, state)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(...marked(text.slice(last), `t${last}`, state));
  return out;
}

const isListItem = (l: string) => /^\s*(-|\d+\.)\s+/.test(l);
const isTableRow = (l: string) => /^\s*\|.*\|\s*$/.test(l);
const cells = (l: string) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

function list(lines: string[], key: number, cite?: Cite, links?: Set<string>): ReactNode {
  const ordered = /^\d+\./.test(lines[0].trim());
  const items: { text: string; children: string[] }[] = [];
  for (const l of lines) {
    if (/^ {4}/.test(l) && items.length) items[items.length - 1].children.push(l.slice(4));
    else items.push({ text: l.replace(/^\s*(-|\d+\.)\s+/, ""), children: [] });
  }
  const body = items.map((it, i) => (
    <li key={i}>{inline(it.text, cite, links)}{it.children.length > 0 && list(it.children, i, cite, links)}</li>
  ));
  return ordered ? <ol key={key}>{body}</ol> : <ul key={key}>{body}</ul>;
}

// `breaks`: keep single line breaks inside paragraphs (extracted document text, OCR lines).
export function Markdown({ source, breaks = false, cite, marks, links }: { source: string; breaks?: boolean; cite?: Cite; marks?: Mark[]; links?: Set<string> }) {
  const lines = (marks?.length ? withMarks(source, marks) : source).replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    if (line.startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      i++;
      blocks.push(<pre key={i}><code>{code.join("\n")}</code></pre>);
      continue;
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      const Tag = (["h1", "h2", "h3"] as const)[h[1].length - 1];
      blocks.push(<Tag key={i}>{inline(h[2], cite, links)}</Tag>);
      i++;
      continue;
    }
    if (line.startsWith(">")) {
      const note: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) note.push(lines[i++].replace(/^>\s?/, ""));
      blocks.push(<div className="notice" key={i}>{inline(note.join(" "), cite, links)}</div>);
      continue;
    }
    if (isTableRow(line)) {
      const rows: string[][] = [];
      while (i < lines.length && isTableRow(lines[i])) {
        if (!/^\s*\|[\s\-:|]+\|\s*$/.test(lines[i])) rows.push(cells(lines[i]));
        i++;
      }
      if (!rows.length) continue; // only separator rows: nothing to show
      const [head, ...body] = rows;
      blocks.push(
        <div className="table-wrap" key={i}>
          <table style={{ minWidth: 0 }}>
            <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, cite, links)}</th>)}</tr></thead>
            <tbody>{body.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j} style={{ height: "auto" }}>{inline(c, cite, links)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (isListItem(line)) {
      const items: string[] = [];
      while (i < lines.length && (isListItem(lines[i]) || /^ {4}\S/.test(lines[i]))) items.push(lines[i++]);
      blocks.push(list(items, i, cite, links));
      continue;
    }
    // The first line always belongs to the paragraph: "#tag" or "| a" match no block above and
    // would otherwise never be consumed (endless loop, frozen tab).
    const para: string[] = [lines[i++]];
    while (i < lines.length && lines[i].trim() && !/^(#|>|```|\s*\||\s*(-|\d+\.)\s)/.test(lines[i])) para.push(lines[i++]);
    blocks.push(
      <p key={i}>
        {breaks ? para.flatMap((l, j) => (j ? [<br key={`b${j}`} />, ...inline(l, cite, links)] : inline(l, cite, links))) : inline(para.join(" "), cite, links)}
      </p>,
    );
  }
  return <div className="prose">{blocks}</div>;
}
