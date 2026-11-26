// Minimal Markdown renderer for the help pages: builds React elements, never injects HTML.
// Supports: # ## ### headings, paragraphs, - and 1. lists (one nested level, 4 spaces),
// > notes, ``` code blocks, | tables |, **bold**, *italic* and `code` inline.
// With `cite`, [n] markers in chat answers become citation links.

import { ReactNode } from "react";

type Cite = (n: number, key: string) => ReactNode;

function inline(text: string, cite?: Cite): ReactNode[] {
  const out: ReactNode[] = [];
  const re = cite ? /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|\[\d{1,3}\])/g : /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const k = `${m.index}`;
    if (tok.startsWith("**")) out.push(<strong key={k}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={k}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("[") && cite) out.push(cite(Number(tok.slice(1, -1)), k));
    else out.push(<em key={k}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const isListItem = (l: string) => /^\s*(-|\d+\.)\s+/.test(l);
const isTableRow = (l: string) => /^\s*\|.*\|\s*$/.test(l);
const cells = (l: string) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

function list(lines: string[], key: number, cite?: Cite): ReactNode {
  const ordered = /^\d+\./.test(lines[0].trim());
  const items: { text: string; children: string[] }[] = [];
  for (const l of lines) {
    if (/^ {4}/.test(l) && items.length) items[items.length - 1].children.push(l.slice(4));
    else items.push({ text: l.replace(/^\s*(-|\d+\.)\s+/, ""), children: [] });
  }
  const body = items.map((it, i) => (
    <li key={i}>{inline(it.text, cite)}{it.children.length > 0 && list(it.children, i, cite)}</li>
  ));
  return ordered ? <ol key={key}>{body}</ol> : <ul key={key}>{body}</ul>;
}

// `breaks`: keep single line breaks inside paragraphs (extracted document text, OCR lines).
export function Markdown({ source, breaks = false, cite }: { source: string; breaks?: boolean; cite?: Cite }) {
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
      blocks.push(<Tag key={i}>{inline(h[2], cite)}</Tag>);
      i++;
      continue;
    }
    if (line.startsWith(">")) {
      const note: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) note.push(lines[i++].replace(/^>\s?/, ""));
      blocks.push(<div className="notice" key={i}>{inline(note.join(" "), cite)}</div>);
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
            <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, cite)}</th>)}</tr></thead>
            <tbody>{body.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j} style={{ height: "auto" }}>{inline(c, cite)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (isListItem(line)) {
      const items: string[] = [];
      while (i < lines.length && (isListItem(lines[i]) || /^ {4}\S/.test(lines[i]))) items.push(lines[i++]);
      blocks.push(list(items, i, cite));
      continue;
    }
    // The first line always belongs to the paragraph: "#tag" or "| a" match no block above and
    // would otherwise never be consumed (endless loop, frozen tab).
    const para: string[] = [lines[i++]];
    while (i < lines.length && lines[i].trim() && !/^(#|>|```|\s*\||\s*(-|\d+\.)\s)/.test(lines[i])) para.push(lines[i++]);
    blocks.push(
      <p key={i}>
        {breaks ? para.flatMap((l, j) => (j ? [<br key={`b${j}`} />, ...inline(l, cite)] : inline(l, cite))) : inline(para.join(" "), cite)}
      </p>,
    );
  }
  return <div className="prose">{blocks}</div>;
}
