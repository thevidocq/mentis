// Minimal Markdown renderer for the help pages: builds React elements, never injects HTML.
// Supports: # ## ### headings, paragraphs, - and 1. lists (one nested level, 4 spaces),
// > notes, ``` code blocks, | tables |, **bold** and `code` inline.

import { ReactNode } from "react";

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    out.push(tok.startsWith("**") ? <strong key={m.index}>{tok.slice(2, -2)}</strong> : <code key={m.index}>{tok.slice(1, -1)}</code>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const isListItem = (l: string) => /^\s*(-|\d+\.)\s+/.test(l);
const isTableRow = (l: string) => /^\s*\|.*\|\s*$/.test(l);
const cells = (l: string) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

function list(lines: string[], key: number): ReactNode {
  const ordered = /^\d+\./.test(lines[0].trim());
  const items: { text: string; children: string[] }[] = [];
  for (const l of lines) {
    if (/^ {4}/.test(l) && items.length) items[items.length - 1].children.push(l.slice(4));
    else items.push({ text: l.replace(/^\s*(-|\d+\.)\s+/, ""), children: [] });
  }
  const body = items.map((it, i) => (
    <li key={i}>{inline(it.text)}{it.children.length > 0 && list(it.children, i)}</li>
  ));
  return ordered ? <ol key={key}>{body}</ol> : <ul key={key}>{body}</ul>;
}

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r/g, "").split("\n");
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
      blocks.push(<Tag key={i}>{inline(h[2])}</Tag>);
      i++;
      continue;
    }
    if (line.startsWith(">")) {
      const note: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) note.push(lines[i++].replace(/^>\s?/, ""));
      blocks.push(<div className="notice" key={i}>{inline(note.join(" "))}</div>);
      continue;
    }
    if (isTableRow(line)) {
      const rows: string[][] = [];
      while (i < lines.length && isTableRow(lines[i])) {
        if (!/^\s*\|[\s\-:|]+\|\s*$/.test(lines[i])) rows.push(cells(lines[i]));
        i++;
      }
      const [head, ...body] = rows;
      blocks.push(
        <div className="table-wrap" key={i}>
          <table style={{ minWidth: 0 }}>
            <thead><tr>{head.map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead>
            <tbody>{body.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j} style={{ height: "auto" }}>{inline(c)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (isListItem(line)) {
      const items: string[] = [];
      while (i < lines.length && (isListItem(lines[i]) || /^ {4}\S/.test(lines[i]))) items.push(lines[i++]);
      blocks.push(list(items, i));
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#|>|```|\s*\||\s*(-|\d+\.)\s)/.test(lines[i])) para.push(lines[i++]);
    blocks.push(<p key={i}>{inline(para.join(" "))}</p>);
  }
  return <div className="prose">{blocks}</div>;
}
