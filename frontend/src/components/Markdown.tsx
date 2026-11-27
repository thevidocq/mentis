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

/** Spans where a mark must not go: fenced code blocks (shown raw), [text](url) links (the URL
 * must stay intact, and a flag button must not sit inside a link), citation markers ("[12]" must
 * stay a citation) and flag tokens already placed. */
function protectedRanges(s: string): [number, number][] {
  const out: [number, number][] = [];
  const fence = /^```[^\n]*\n[\s\S]*?(?:^```[^\n]*$|(?![\s\S]))/gm;
  for (const m of s.matchAll(fence)) out.push([m.index ?? 0, (m.index ?? 0) + m[0].length]);
  for (const re of [/\[[^\]\n]{1,300}\]\([^\s)]{1,1000}\)/g, /\[\d{1,3}\]/g, /\uE002[^\uE003]*\uE003/g]) {
    for (const m of s.matchAll(re)) out.push([m.index ?? 0, (m.index ?? 0) + m[0].length]);
  }
  return out;
}

/** A mark: the text to underline and, for a value, the statement it belongs to (the same value
 * may appear elsewhere in the answer, correct). */
export type Mark = { text: string; within?: string };

const WORD = /[\p{L}\p{N}]/u;

/** Whether s[at, at+len) starts and ends on word edges ("5 minutes" is not inside "15 minutes"). */
function onEdges(s: string, at: number, len: number): boolean {
  const m = s.slice(at, at + len);
  const before = at > 0 ? s[at - 1] : "";
  const after = s[at + len] ?? "";
  return !(WORD.test(m[0]) && before && WORD.test(before)) && !(WORD.test(m[m.length - 1]) && after && WORD.test(after));
}

/** The first occurrence of `m` outside protected spans and on word edges, from `from` to `to`, or -1. */
function findFree(s: string, m: string, from = 0, to = s.length): number {
  const ranges = protectedRanges(s);
  for (let at = s.indexOf(m, from); at >= 0 && at + m.length <= to; at = s.indexOf(m, at + 1)) {
    if (!ranges.some(([a, b]) => at < b && at + m.length > a) && onEdges(s, at, m.length)) return at;
  }
  return -1;
}

const balanced = (s: string, at: number) => s.slice(0, at).split(OPEN).length === s.slice(0, at).split(CLOSE).length;

/** Insert highlight markers around the first free occurrence of each mark (longest first), then a
 * flag token after the citations that follow it, or that follow its statement for a value
 * ("text [2]" -> "OPEN text CLOSE [2] FLAG"). */
function withMarks(source: string, marks: Mark[]): string {
  let s = source;
  const order = marks.map((m, k) => ({ text: m.text.replace(PRIVATE, ""), within: m.within?.replace(PRIVATE, ""), k }))
    .filter((m) => m.text && m.text.trim().length > 1)
    .sort((a, b) => b.text.length - a.text.length);
  const seen = new Set<string>();
  for (const { text: m, within, k } of order) {
    const id = `${m}\u0000${within ?? ""}`;
    if (seen.has(id)) continue;
    seen.add(id);
    let at = -1;
    let stmtEnd = -1;
    if (within && within.trim().length > 1) {
      // The statement first (markers already placed in it are skipped by comparing without them).
      const plain = s.replace(/[\uE000\uE001]|\uE002[^\uE003]*\uE003/g, "");
      const sAt = plain.indexOf(within);
      if (sAt >= 0) {
        // Map the statement's span back to `s` (which may hold markers).
        let i = 0, j = 0, start = -1, end = -1;
        while (i <= s.length) {
          if (j === sAt && start < 0) start = i;
          if (j === sAt + within.length) { end = i; break; }
          if (i === s.length) break;
          const c = s[i];
          if (c === OPEN || c === CLOSE) { i++; continue; }
          if (c === "\uE002") { i = s.indexOf("\uE003", i) + 1; continue; }
          i++; j++;
        }
        if (start >= 0 && end >= 0) {
          at = findFree(s, m, start, end);
          stmtEnd = end;
        }
      }
    }
    if (at < 0) at = findFree(s, m);
    if (at < 0 || !balanced(s, at)) continue; // not found, or inside another
    if (s.slice(at, at + m.length).includes(OPEN) || s.slice(at, at + m.length).includes(CLOSE)) continue;
    const end = at + m.length;
    const after = stmtEnd > end && balanced(s, stmtEnd) ? stmtEnd : end;
    const tail = /^(?:\*\*|\*|`)?((?:[ \t]*\[\d{1,3}\])*)/.exec(s.slice(after))!; // after a closing **, * or `; same line only
    const cites = [...tail[1].matchAll(/\d{1,3}/g)].map((x) => x[0]).join(",");
    const flagAt = after + tail[0].length + 2; // +2: OPEN and CLOSE are inserted before it
    s = s.slice(0, at) + OPEN + m + CLOSE + s.slice(end);
    s = s.slice(0, flagAt) + `\uE002${k}:${cites}\uE003` + s.slice(flagAt);
  }
  return s;
}

/** Where each mark was placed (true) or not found in the text (false). */
export function placedMarks(source: string, marks: Mark[]): boolean[] {
  const s = withMarks(source.replace(PRIVATE, ""), marks);
  return marks.map((_, k) => s.includes(`\uE002${k}:`));
}

const LINK = /^\[([^\]\n]{1,300})\]\((https?:\/\/[^\s)]{1,1000})\)$/;

function inline(text: string, cite?: Cite, links?: Set<string>, flag?: Flag,
                state: { open: boolean; flag?: Flag } = { open: false, flag }, prefix = ""): ReactNode[] {
  const out: ReactNode[] = [];
  const link = "\\[[^\\]\\n]{1,300}\\]\\(https?:\\/\\/[^\\s)]{1,1000}\\)|";
  const re = new RegExp(`(${links ? link : ""}\\*\\*[^*]+\\*\\*|\`[^\`]+\`|\\*[^*\\s][^*]*\\*${cite ? "|\\[\\d{1,3}\\]" : ""})`, "g");
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(...marked(text.slice(last, m.index), `${prefix}t${last}`, state));
    const tok = m[0];
    const k = `${prefix}${m.index}`;
    const l = links && tok.startsWith("[") ? LINK.exec(tok) : null;
    if (l) {
      out.push(links!.has(l[2])
        ? <a key={k} href={l[2]} target="_blank" rel="noopener noreferrer nofollow" className="record-inline-link">{marked(l[1], k, state)}</a>
        : <span key={k}>{marked(l[1], k, state)}</span>);
    } else if (tok.startsWith("**")) out.push(<strong key={k}>{inline(tok.slice(2, -2), cite, links, flag, state, `${k}.`)}</strong>); // [n] inside bold stays a citation
    else if (tok.startsWith("`")) out.push(<code key={k}>{marked(tok.slice(1, -1), k, state)}</code>);
    else if (tok.startsWith("[") && cite) out.push(cite(Number(tok.slice(1, -1)), k));
    else out.push(<em key={k}>{inline(tok.slice(1, -1), cite, links, flag, state, `${k}.`)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(...marked(text.slice(last), `${prefix}t${last}`, state));
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
export function Markdown({ source, breaks = false, cite, marks, links, flag }: { source: string; breaks?: boolean; cite?: Cite; marks?: Mark[]; links?: Set<string>; flag?: Flag }) {
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
