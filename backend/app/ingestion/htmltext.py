"""Web pages to Markdown, for documentation added from a link.

Only the content is kept: the page's <main> when it has one (else <body>), without scripts, styles,
navigation, sidebars, form controls and hidden elements; the site's header and footer are left out,
but a <header> inside the content (an article title) is kept. Headings become "#" lines, lists "-" or
"1." items (nested up to a few levels), tables Markdown tables, <pre> fenced code blocks; links keep
their text only (an address in a page is data, never a link in an answer). lxml, already a dependency.

Bounded: the output stops at `max_chars` and nesting is capped, so a crafted page cannot turn a few
kilobytes of HTML into gigabytes of text.
"""

import re

from lxml import etree
from lxml import html as lxml_html

from app.ingestion.text import markdown_table, normalize_text

SKIP = {"script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "embed", "nav", "aside",
        "button", "select", "input", "textarea", "dialog", "menu", "head", "title", "meta", "link"}
CHROME = {"header", "footer"}           # the site's own header and footer, outside the content
BLOCKS = {"p", "div", "section", "article", "main", "blockquote", "figure", "figcaption", "dl", "dd", "dt",
          "details", "summary", "address", "form", "fieldset", "header", "footer", "body", "html", "center"}
LISTS = {"ul", "ol"}
MAX_LIST_DEPTH = 6
MAX_DEPTH = 200
MAX_INLINE_DEPTH = 32   # deeper inline markup is read as plain text (keeps the cost linear)
ANCHOR_CLASSES = ("headerlink", "hash-link", "anchor", "heading-anchor", "anchorjs-link")


class _Out:
    """Collected blocks with a running size cap."""

    def __init__(self, max_chars: int):
        self.parts: list[str] = []
        self.left = max_chars
        self.full = False

    def add(self, text: str) -> None:
        text = text.strip("\n")
        if not text.strip() or self.full:
            return
        if len(text) > self.left:
            text, self.full = text[: max(self.left, 0)], True
        self.left -= len(text) + 2
        self.parts.append(text)


def _tag(el) -> str:
    return el.tag.lower() if isinstance(el.tag, str) else ""


def _anchor(el) -> bool:
    """A heading's permalink ("¶", "#"): site furniture, not content."""
    if _tag(el) != "a":
        return False
    classes = (el.get("class") or "").lower().split()
    return any(c in classes for c in ANCHOR_CLASSES)


def _clean_heading(text: str) -> str:
    return re.sub(r"[\u00b6\u200b\ufeff]", "", text).strip().rstrip("#").strip()


def _hidden(el) -> bool:
    style = (el.get("style") or "").replace(" ", "").lower()
    return el.get("hidden") is not None or el.get("aria-hidden") == "true" or "display:none" in style


def _is_block(el) -> bool:
    t = _tag(el)
    return t in BLOCKS or t in LISTS or t in ("pre", "table", "hr", "li", "tr") or bool(re.fullmatch(r"h[1-6]", t))


def _inline(el, depth: int = 0) -> str:
    """The text of an element on one line, with **bold**, *italic* and `code`; blocks inside it
    (paragraphs in a list item, say) are separated by a space."""
    if depth > MAX_INLINE_DEPTH:
        return el.text_content()
    parts = [el.text or ""]
    for child in el:
        tag = _tag(child)
        if not tag or tag in SKIP or _hidden(child) or _anchor(child):
            parts.append(child.tail or "")
            continue
        inner = _inline(child, depth + 1)
        if tag in ("strong", "b") and inner.strip():
            inner = f"**{inner.strip()}**"
        elif tag in ("em", "i") and inner.strip():
            inner = f"*{inner.strip()}*"
        elif tag == "code" and inner.strip():
            inner = f"`{inner.strip()}`"
        elif tag == "br":
            inner = " "
        elif tag == "img":
            inner = (child.get("alt") or "").strip()
        elif _is_block(child):
            inner = f" {inner} "
        parts.append(inner)
        parts.append(child.tail or "")
    text = "".join(parts)
    return re.sub(r"\s+", " ", text) if depth == 0 else text


def _inline_one(child, depth: int) -> str:
    """One inline element with its formatting (bold, code...), without its tail."""
    tag = _tag(child)
    inner = _inline(child, depth)
    if tag in ("strong", "b") and inner.strip():
        return f"**{inner.strip()}**"
    if tag in ("em", "i") and inner.strip():
        return f"*{inner.strip()}*"
    if tag == "code" and inner.strip():
        return f"`{inner.strip()}`"
    if tag == "br":
        return " "
    if tag == "img":
        return (child.get("alt") or "").strip()
    return inner


def _rows(table) -> list:
    """The table's own rows (not those of a table nested in a cell)."""
    out = []
    for child in table:
        t = _tag(child)
        if t == "tr":
            out.append(child)
        elif t in ("thead", "tbody", "tfoot"):
            out.extend(c for c in child if _tag(c) == "tr")
    return out


def _span(cell, name: str) -> int:
    value = (cell.get(name) or "1").strip()
    return min(int(value), 50) if value.isdigit() and int(value) > 0 else 1


def _table(el) -> str:
    """The table as a grid: a cell spanning rows or columns fills every slot it covers, so the
    values below a "Tier 2" cell spanning two rows stay in their own columns."""
    grid: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}  # column -> (text, rows still covered)
    for tr in _rows(el)[:5000]:
        row: list[str] = []
        cells = [c for c in tr if _tag(c) in ("td", "th")]
        col = 0

        def fill_pending():
            nonlocal col
            while col in pending:
                text, left = pending[col]
                row.append(text)
                if left <= 1:
                    del pending[col]
                else:
                    pending[col] = (text, left - 1)
                col += 1

        for c in cells:
            fill_pending()
            text = _inline(c).strip()
            rows_down, cols = _span(c, "rowspan"), _span(c, "colspan")
            for _ in range(cols):
                row.append(text)
                if rows_down > 1:
                    pending[col] = (text, rows_down - 1)
                col += 1
        fill_pending()
        if any(row):
            grid.append(row)
    return markdown_table(grid) if grid else ""


def _list(el, out: _Out, depth: int, level: int) -> None:
    """Items as "-" or "1." lines; inside an item, text is one line, while nested lists, code blocks
    and tables keep their own blocks, indented under the item, in their order."""
    start = el.get("start") or ""
    n = int(start) - 1 if start.isdigit() and len(start) < 7 else 0
    indent = "    " * min(level, MAX_LIST_DEPTH)
    for li in el:
        if out.full or depth > MAX_DEPTH:
            return
        if _tag(li) != "li" or _hidden(li):
            continue
        n += 1
        marker = f"{n}." if _tag(el) == "ol" else "-"
        first = True
        run = [li.text or ""]

        def flush() -> None:
            nonlocal first
            text = re.sub(r"\s+", " ", "".join(run)).strip()
            run.clear()
            if text:
                out.add(f"{indent}{marker} {text}" if first else f"{indent}    {text}")
                first = False

        for c in li:
            t = _tag(c)
            if not t or t in SKIP or _hidden(c) or _anchor(c):
                run.append(c.tail or "")
                continue
            if t in LISTS or t in ("pre", "table"):
                if first and not re.sub(r"\s+", "", "".join(run)):
                    out.add(f"{indent}{marker}")  # an item that starts with a block still gets its marker
                    first = False
                flush()
                if t in LISTS:
                    _list(c, out, depth + 1, level + 1)
                else:
                    sub = _Out(out.left)
                    _blocks(_wrap(c), sub, depth + 1, True)
                    for block in sub.parts:
                        out.add("\n".join(f"{indent}    {line}" for line in block.split("\n")))
                run.append(c.tail or "")
                continue
            run.append(f" {_inline(c, depth + 1)} " if _is_block(c) else _inline_one(c, depth + 1))
            run.append(c.tail or "")
        flush()


def _wrap(el):
    """A copy of `el` inside a <div>, to read it as a block on its own."""
    div = lxml_html.Element("div")
    copy = el.__copy__()
    copy.tail = None
    div.append(copy)
    return div


def _blocks(el, out: _Out, depth: int = 0, content: bool = False) -> None:
    """Block children as Markdown blocks; inline runs between them become one paragraph."""
    if depth > MAX_DEPTH or out.full:
        return
    run: list[str] = [el.text or ""]

    def flush() -> None:
        text = re.sub(r"\s+", " ", "".join(run)).strip()
        run.clear()
        if text:
            out.add(text)

    for child in el:
        tag = _tag(child)
        if not tag or tag in SKIP or _hidden(child) or _anchor(child) or (tag in CHROME and not content):
            run.append(child.tail or "")
            continue
        if not _is_block(child):
            run.append(_inline_one(child, depth + 1))
            run.append(child.tail or "")
            continue
        flush()
        if re.fullmatch(r"h[1-6]", tag):
            text = _clean_heading(_inline(child))
            if text:
                out.add(f"{'#' * int(tag[1])} {text}")
        elif tag in LISTS:
            _list(child, out, depth + 1, 0)
        elif tag == "pre":
            code = child.text_content().strip("\n")
            if code.strip():
                fence = "`" * max(3, 1 + max((len(m) for m in re.findall(r"`+", code)), default=0))
                classes = (child.get("class") or "").split() + ((child[0].get("class") or "").split() if len(child) else [])
                lang = next((c[9:] for c in classes if c.startswith("language-")), "")
                out.add(f"{fence}{re.sub(r'[^A-Za-z0-9_+-]', '', lang)}\n{code}\n{fence}")
        elif tag == "table":
            md = _table(child)
            if md:
                out.add(md)
        elif tag == "hr":
            out.add("---")
        elif tag == "blockquote":
            sub = _Out(out.left)
            _blocks(child, sub, depth + 1, content)
            for block in sub.parts:
                out.add("\n".join(f"> {line}" if line.strip() else ">" for line in block.split("\n")))
        else:
            _blocks(child, out, depth + 1, content or tag in ("main", "article"))
        run.append(child.tail or "")
    flush()


def _charset(content_type: str | None) -> str | None:
    m = re.search(r"charset=\"?([\w.:-]{1,40})", content_type or "", re.IGNORECASE)
    return m.group(1) if m else None


def to_markdown(data: bytes, content_type: str | None = None, max_chars: int = 5_000_000) -> tuple[str, str | None]:
    """(Markdown, page title or None). ValueError when the page has no readable content."""
    charset = _charset(content_type)
    if charset is None and not re.search(rb"<meta[^>]+charset", data[:4096], re.IGNORECASE):
        try:  # no charset said anywhere: UTF-8 when the bytes are UTF-8 (lxml would guess Latin-1)
            data.decode("utf-8")
            charset = "utf-8"
        except UnicodeDecodeError:
            pass
    try:
        # huge_tree: a long text node is fine here, the input is already capped (20 MB)
        doc = lxml_html.document_fromstring(data, parser=lxml_html.HTMLParser(encoding=charset, huge_tree=True))
    except (ValueError, LookupError, etree.ParserError):
        raise ValueError("the page could not be read") from None
    title_el = doc.find(".//title")
    title = re.sub(r"\s+", " ", title_el.text_content()).strip()[:200] if title_el is not None else None
    main = doc.find(".//main")
    body = doc.find(".//body")
    use_main = main is not None and not _hidden(main)
    root = main if use_main else (body if body is not None else doc)
    out = _Out(max_chars)
    _blocks(root, out, content=use_main)
    text = normalize_text("\n\n".join(out.parts))
    if not text.strip():
        raise ValueError("the page has no readable text (it may need JavaScript)")
    if title and not text.lstrip().startswith("#"):
        text = f"# {title}\n\n{text}"
    if out.full:
        text += "\n\n*The page is longer than the size limit: the rest was not read.*"
    return text, title or None
