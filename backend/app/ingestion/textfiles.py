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

from app.ingestion.text import fenced_lines, markdown_table, normalize_text
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

def _heading(line: str, top: str) -> str | None:
    """The title of a `top`-level heading line, or None. Closing hashes go only after a space
    ("# C#" stays "C#"). No regex over the title: cost stays linear on long runs of spaces."""
    if not line.startswith(top) or len(line) <= len(top) or not line[len(top)].isspace():
        return None
    title = line[len(top):].strip()
    bare = title.rstrip("#")
    if bare != title and (not bare or bare[-1].isspace()):
        title = bare.rstrip()
    return title or None


def parse_md(data: bytes, limits: ParseLimits) -> ParseResult:
    lines = decode(data).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    in_code = fenced_lines(lines)
    top = None
    for line, code in zip(lines, in_code):  # the split level: "#" if any, else "##"
        if code:
            continue
        if re.match(r"^#\s+\S", line):
            top = "#"
            break
        if re.match(r"^##\s+\S", line):
            top = "##"
    sections: list[tuple[str, list[str]]] = []
    label, body = "Beginning", []
    for line, code in zip(lines, in_code):
        title = None if code or top is None else _heading(line, top)
        if title:
            if any(x.strip() for x in body):
                sections.append((label, body))
            label, body = title[:110], [line]
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
            more = [f"{pad}… {len(value) - MAX_ITEMS} more rows not read"] if len(value) > MAX_ITEMS else []
            return [markdown_table([keys] + [[i.get(k) for k in keys] for i in value[:MAX_ITEMS]]), *more]
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


_FLAGS = {"low_confidence", "merged_cells", "truncated"}  # "empty" is recomputed


def _exported_page(p: dict, index: int) -> ExtractedPage:
    """A page of a Mentis export with its quality signals (OCR, confidence, tables, flags) kept."""
    kind = p.get("kind") if p.get("kind") in KINDS else "section"
    conf = p.get("ocr_confidence")
    try:  # numbers are read as written (strings) by parse_json
        conf = float(conf) if isinstance(conf, (int, float, str)) and not isinstance(conf, bool) else None
    except ValueError:
        conf = None
    conf = conf if conf is not None and 0 <= conf <= 1 else None
    tables = p.get("tables")
    page = ExtractedPage(index=index, kind=kind, label=str(p.get("label") or f"{kind.title()} {index}")[:110],
                         text=normalize_text(str(p.get("text") or "")),
                         method="ocr" if p.get("method") == "ocr" else "native", ocr_confidence=conf,
                         tables=tables if isinstance(tables, int) and not isinstance(tables, bool) and 0 <= tables < 100_000 else 0,
                         flags=[f for f in dict.fromkeys(p.get("flags") or []) if f in _FLAGS] if isinstance(p.get("flags"), list) else [])
    page.finalize()
    page.flags = list(dict.fromkeys(page.flags))
    return page


def parse_json(data: bytes, limits: ParseLimits) -> ParseResult:
    doc = json.loads(decode(data), parse_float=str)  # numbers as written: "1.10" stays 1.10, not 1.1
    if isinstance(doc, dict) and doc.get("format") == MENTIS_JSON and isinstance(doc.get("pages"), list):
        pages = []
        for p in doc["pages"][: limits.max_pages]:
            if not isinstance(p, dict):
                continue
            pages.append(_exported_page(p, len(pages) + 1))
        warnings = ["Read from a Mentis export: pages as exported."]
        if len(doc["pages"]) > limits.max_pages:
            warnings.append(f"Only the first {limits.max_pages} of {len(doc['pages'])} pages were read.")
        return ParseResult(pages or [ExtractedPage(index=1, kind="section", label="Beginning", text="").finalize()], warnings)
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
