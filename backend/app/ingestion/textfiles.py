"""Markdown and JSON documents.

- Markdown: one section per top-level heading (`#`, or `##` when the file has no `#`), headings
  inside code blocks ignored, the text kept as written.
- JSON: a Mentis export (`"format": "mentis-document/1"`, see Documents → download) is read back
  with its own pages, so documentation moves between customers or installations without loss.
  Any other JSON becomes readable Markdown: one section per top-level key (object) or per item
  (array of objects), nested values as indented lists, arrays of flat objects as tables.
"""

import json
import re

from app.ingestion.text import markdown_table, normalize_text
from app.ingestion.types import ExtractedPage, ParseLimits, ParseResult

MENTIS_JSON = "mentis-document/1"
KINDS = {"page", "section", "slide", "sheet"}
MAX_DEPTH = 12              # nested levels rendered; deeper values are summarised
MAX_ITEMS = 2000            # list items rendered per list
LABEL_KEYS = ("title", "name", "label", "id", "key", "number")


def decode(data: bytes) -> str:
    """UTF-8 text (with or without BOM); raises ValueError for anything else."""
    if b"\x00" in data:
        raise ValueError("binary content")
    return data.decode("utf-8-sig")


# --- Markdown -----------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*(```|~~~)")


def parse_md(data: bytes, limits: ParseLimits) -> ParseResult:
    lines = decode(data).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fenced, top = False, None
    for line in lines:  # the split level: "#" if any, else "##"
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced and re.match(r"^#\s+\S", line):
            top = "#"
            break
        elif not fenced and re.match(r"^##\s+\S", line):
            top = top or "##"
    sections: list[tuple[str, list[str]]] = []
    label, body, fenced = "Beginning", [], False
    for line in lines:
        if _FENCE.match(line):
            fenced = not fenced
        m = None if fenced or top is None else re.match(rf"^{re.escape(top)}\s+(.+?)\s*#*\s*$", line)
        if m:
            if any(x.strip() for x in body):
                sections.append((label, body))
            label, body = m.group(1)[:110], [line]
        else:
            body.append(line)
    if any(x.strip() for x in body) or not sections:
        sections.append((label, body))
    pages = [ExtractedPage(index=i + 1, kind="section", label=lbl, text=normalize_text("\n".join(b)),
                           tables=sum(1 for x in b if re.match(r"^\s*\|\s*-{3}", x))).finalize()
             for i, (lbl, b) in enumerate(sections[: limits.max_pages])]
    warnings = [f"Only the first {limits.max_pages} sections were read."] if len(sections) > limits.max_pages else []
    return ParseResult(pages, warnings)


# --- JSON ---------------------------------------------------------------------------------

def _scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _flat_objects(items: list) -> bool:
    return bool(items) and all(isinstance(i, dict) and all(not isinstance(x, (dict, list)) for x in i.values()) for i in items)


def _render(value, depth: int = 0) -> list[str]:
    pad = "  " * depth
    if depth > MAX_DEPTH:
        return [f"{pad}- …"]
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}- **{k}**:")
                out += _render(v, depth + 1)
            else:
                out.append(f"{pad}- **{k}**: {_scalar(v) if not isinstance(v, (dict, list)) else ''}".rstrip())
        return out
    if isinstance(value, list):
        if depth <= 1 and _flat_objects(value):
            keys = list(dict.fromkeys(k for i in value[:MAX_ITEMS] for k in i))
            return [markdown_table([keys] + [[i.get(k) for k in keys] for i in value[:MAX_ITEMS]])]
        out = []
        for item in value[:MAX_ITEMS]:
            if isinstance(item, (dict, list)):
                out.append(f"{pad}-")
                out += _render(item, depth + 1)
            else:
                out.append(f"{pad}- {_scalar(item)}")
        if len(value) > MAX_ITEMS:
            out.append(f"{pad}- … {len(value) - MAX_ITEMS} more")
        return out
    return [f"{pad}{_scalar(value)}"]


def _label(item, n: int) -> str:
    if isinstance(item, dict):
        for k in LABEL_KEYS:
            if isinstance(item.get(k), (str, int)) and str(item[k]).strip():
                return str(item[k]).strip()[:110]
    return f"Item {n}"


def parse_json(data: bytes, limits: ParseLimits) -> ParseResult:
    doc = json.loads(decode(data))
    if isinstance(doc, dict) and doc.get("format") == MENTIS_JSON and isinstance(doc.get("pages"), list):
        pages = []
        for p in doc["pages"][: limits.max_pages]:
            if not isinstance(p, dict):
                continue
            kind = p.get("kind") if p.get("kind") in KINDS else "section"
            label = str(p.get("label") or f"{kind.title()} {len(pages) + 1}")[:110]
            pages.append(ExtractedPage(index=len(pages) + 1, kind=kind, label=label,
                                       text=normalize_text(str(p.get("text") or ""))).finalize())
        return ParseResult(pages or [ExtractedPage(index=1, kind="section", label="Beginning", text="").finalize()],
                           ["Read from a Mentis export: pages as exported."])
    if isinstance(doc, dict):
        parts = list(doc.items())
        sections = [(str(k)[:110], v) for k, v in parts]
    elif isinstance(doc, list) and doc and all(isinstance(i, dict) for i in doc):
        sections = [(_label(item, n), item) for n, item in enumerate(doc, start=1)]
    else:
        sections = [("Beginning", doc)]
    pages = []
    for lbl, value in sections[: limits.max_pages]:
        body = _render(value)
        pages.append(ExtractedPage(index=len(pages) + 1, kind="section", label=lbl,
                                   text=normalize_text("\n".join([f"## {lbl}", *body])),
                                   tables=sum(1 for b in body if b.startswith("| "))).finalize())
    warnings = [f"Only the first {limits.max_pages} sections were read."] if len(sections) > limits.max_pages else []
    return ParseResult(pages, warnings)
