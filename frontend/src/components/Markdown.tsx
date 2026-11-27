// Minimal Markdown renderer for the help pages: builds React elements, never injects HTML.
// Supports: # ## ### headings, paragraphs, - and 1. lists (one nested level, 4 spaces),
// > notes, ``` code blocks, | tables |, **bold**, *italic* and `code` inline.
// With `cite`, [n] markers in chat answers become citation links. With `marks`, those exact
// passages of the source are underlined (answer check findings) and, with `flag`, followed by a
// small marker after their citations (flag(k, cites): k = index in `marks`). With `links`, [text](url) becomes
// a link only when url is one of them (the pages of live records); any other address stays text.

import { ReactNode } from "react";

type Cite = (n: number, key: string) => ReactNode;

const OPEN = "\uE000";
const CLOSE = "\uE001";
const FLAG = /(\uE002[\d,:]+\uE003)/;  // \uE002<k>:<cites>\uE003, placed after a mark and its citations

export type Flag = (k: number, cites: number[], key: string) => ReactNode;

/** Text with highlight markers -> nodes; `state.open` carries a highlight across bold or code. */
function marked(text: string, key: string, state: { open: boolean; flag?: Flag }): ReactNode[] {
  if (FLAG.test(text)) {
    return text.split(FLAG).flatMap((part, i) => {
      if (!FLAG.test(part)) return part ? marked(part, `${key}f${i}`, state) : [];
      const [k, cites] = part.slice(1, -1).split(":");
      return state.flag ? [state.flag(Number(k), cites ? cites.split(",").map(Number) : [], `${key}g${i}`)] : [];
    });
  }
  if (!text.includes(OPEN) && !text.includes(CLOSE)) return [state.open ? <mark key={key} className="check-mark">{text}</mark> : text];
  const out: ReactNode[] = [];
  text.split(/([\uE000\uE001])/).forEach((part, i) => {
    if (part === OPEN) state.open = true;
    else if (part === CLOSE) state.open = false;
    else if (part) out.push(state.open ? <mark key={`${key}m${i}`} className="check-mark">{part}</mark> : part);
  });
  return out;
}

const PRIVATE = /[\uE000-\uE003]/g; // our marker characters: never taken from the text itself

/** Spans where a mark must not go: fenced code blocks (shown raw) and [text](url) links (the URL
 * must stay intact, and a flag button must not sit inside a link). */
function protectedRanges(s: string): [number, number][] {
  const out: [number, number][] = [];
  const fence = /^```[^\n]*\n[\s\S]*?(?:^```[^\n]*$|(?![\s\S]))/gm;
  for (const m of s.matchAll(fence)) out.push([m.index ?? 0, (m.index ?? 0) + m[0].length]);
  for (const m of s.matchAll(/\[[^\]\n]{1,300}\]\([^\s)]{1,1000}\)/g)) out.push([m.index ?? 0, (m.index ?? 0) + m[0].length]);
  return out;
}

/** The first occurrence of `m` outside protected spans, or -1. */
function findFree(s: string, m: string): number {
  const ranges = protectedRanges(s);
  for (let at = s.indexOf(m); at >= 0; at = s.indexOf(m, at + 1)) {
    if (!ranges.some(([a, b]) => at < b && at + m.length > a)) return at;
  }
  return -1;
}

/** Insert highlight markers around the first free occurrence of each mark (longest first), then a
 * flag token after the citations that follow it ("text [2]" -> "OPEN text CLOSE [2] FLAG"). */
function withMarks(source: string, marks: string[]): string {
  let s = source;
  const order = marks.map((text, k) => ({ text, k })).filter((m) => m.text && m.text.trim().length > 1)
    .sort((a, b) => b.text.length - a.text.length);
  const seen = new Set<string>();
  for (const { text: m, k } of order) {
    if (seen.has(m)) continue;
    seen.add(m);
    const at = findFree(s, m);
    if (at < 0 || s.slice(0, at).split(OPEN).length !== s.slice(0, at).split(CLOSE).length) continue; // not found, or inside another
    if (s.slice(at, at + m.length).includes(OPEN) || s.slice(at, at + m.length).includes(CLOSE)) continue;
    const end = at + m.length;
    const tail = /^(?:\*\*)?((?:\s*\[\d{1,3}\])*)/.exec(s.slice(end))!;
    const cites = [...tail[1].matchAll(/\d{1,3}/g)].map((x) => x[0]).join(",");
    const flagAt = end + tail[0].length;
    s = s.slice(0, at) + OPEN + m + CLOSE + s.slice(end, flagAt) + `\uE002${k}:${cites}\uE003` + s.slice(flagAt);
  }
  return s;
}

/** Where each mark was placed (true) or not found in the text (false). */
export function placedMarks(source: string, marks: string[]): boolean[] {
  const s = withMarks(source.replace(PRIVATE, ""), marks);
  return marks.map((_, k) => s.includes(`\uE002${k}:`));
}

const LINK = /^\[([^\]\n]{1,300})\]\((https?:\/\/[^\s)]{1,1000})\)$/;

function inline(text: string, cite?: Cite, links?: Set<string>, flag?: Flag): ReactNode[] {
  const state: { open: boolean; flag?: Flag } = { open: false, flag };
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

function list(lines: string[], key: number, cite?: Cite, links?: Set<string>, flag?: Flag): ReactNode {
  const ordered = /^\d+\./.test(lines[0].trim());
  const items: { text: string; children: string[] }[] = [];
  for (const l of lines) {
    if (/^ {4}/.test(l) && items.length) items[items.length - 1].children.push(l.slice(4));
    else items.push({ text: l.replace(/^\s*(-|\d+\.)\s+/, ""), children: [] });
  }
  const body = items.map((it, i) => (
    <li key={i}>{inline(it.text, cite, links, flag)}{it.children.length > 0 && list(it.children, i, cite, links, flag)}</li>
  ));
  return ordered ? <ol key={key}>{body}</ol> : <ul key={key}>{body}</ul>;
}

// `breaks`: keep single line breaks inside paragraphs (extracted document text, OCR lines).
export function Markdown({ source, breaks = false, cite, marks, links, flag }: { source: string; breaks?: boolean; cite?: Cite; marks?: string[]; links?: Set<string>; flag?: Flag }) {
  const clean = source.replace(PRIVATE, ""); // e.g. icon-font characters from a PDF: plain text, not markers
  const lines = (marks?.length ? withMarks(clean, marks) : clean).replace(/\r/g, "").split("\n");
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
      blocks.push(<Tag key={i}>{inline(h[2], cite, links, flag)}</Tag>);
      i++;
      continue;
    }
    if (line.startsWith(">")) {
      const note: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) note.push(lines[i++].replace(/^>\s?/, ""));
      blocks.push(<div className="notice" key={i}>{inline(note.join(" "), cite, links, flag)}</div>);
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
            <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, cite, links, flag)}</th>)}</tr></thead>
            <tbody>{body.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j} style={{ height: "auto" }}>{inline(c, cite, links, flag)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (isListItem(line)) {
      const items: string[] = [];
      while (i < lines.length && (isListItem(lines[i]) || /^ {4}\S/.test(lines[i]))) items.push(lines[i++]);
      blocks.push(list(items, i, cite, links, flag));
      continue;
    }
    // The first line always belongs to the paragraph: "#tag" or "| a" match no block above and
    // would otherwise never be consumed (endless loop, frozen tab).
    const para: string[] = [lines[i++]];
    while (i < lines.length && lines[i].trim() && !/^(#|>|```|\s*\||\s*(-|\d+\.)\s)/.test(lines[i])) para.push(lines[i++]);
    blocks.push(
      <p key={i}>
        {breaks ? para.flatMap((l, j) => (j ? [<br key={`b${j}`} />, ...inline(l, cite, links, flag)] : inline(l, cite, links, flag))) : inline(para.join(" "), cite, links, flag)}
      </p>,
    );
  }
  return <div className="prose">{blocks}</div>;
}
