"""Web pages to Markdown, for documentation added from a link.

Only the content is kept: the page's <main> or <article> when it has one (else <body>), without
scripts, styles, navigation, headers, footers, sidebars, forms and hidden elements. Headings become
"#" lines, lists "-" or "1." items, tables Markdown tables, <pre> fenced code blocks; links keep their
text only (an address in a page is data, never a link in an answer). lxml, already a dependency.
"""

import re

from lxml import html as lxml_html

from app.ingestion.text import markdown_table, normalize_text

SKIP = {"script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "embed", "nav",
        "header", "footer", "aside", "form", "button", "select", "input", "textarea", "dialog", "menu"}
BLOCKS = {"p", "div", "section", "article", "main", "blockquote", "figure", "figcaption", "dl", "dd", "dt",
          "details", "summary", "address"}
MAX_DEPTH = 200


def _hidden(el) -> bool:
    style = (el.get("style") or "").replace(" ", "").lower()
    return el.get("hidden") is not None or el.get("aria-hidden") == "true" or "display:none" in style


def _inline(el, depth: int = 0) -> str:
    """The text of an element on one line, with **bold**, *italic* and `code`."""
    if depth > MAX_DEPTH:
        return ""
    parts = [el.text or ""]
    for child in el:
        tag = child.tag if isinstance(child.tag, str) else ""
        if tag in SKIP or _hidden(child):
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
        parts.append(inner)
        parts.append(child.tail or "")
    return re.sub(r"\s+", " ", "".join(parts))


def _table(el) -> str:
    rows = []
    for tr in el.iter("tr"):
        cells = [_inline(c).strip() for c in tr if isinstance(c.tag, str) and c.tag in ("td", "th")]
        if any(cells):
            rows.append(cells)
    return markdown_table(rows) if rows else ""


def _blocks(el, out: list[str], depth: int = 0, list_prefix: str = "") -> None:
    if depth > MAX_DEPTH:
        return
    if el.text and el.text.strip():
        out.append(re.sub(r"\s+", " ", el.text.strip()))
    for child in el:
        tag = child.tag if isinstance(child.tag, str) else ""
        if tag in SKIP or _hidden(child) or not tag:
            pass
        elif re.fullmatch(r"h[1-6]", tag):
            text = _inline(child).strip()
            if text:
                out.append(f"{'#' * int(tag[1])} {text}")
        elif tag in ("ul", "ol"):
            n = 0
            for li in child:
                if not isinstance(li.tag, str) or li.tag != "li":
                    continue
                n += 1
                marker = f"{n}." if tag == "ol" else "-"
                nested = [c for c in li if isinstance(c.tag, str) and c.tag in ("ul", "ol")]
                for c in nested:
                    li.remove(c)  # nested lists follow their item, indented
                text = _inline(li).strip()
                if text:
                    out.append(f"{list_prefix}{marker} {text}")
                for c in nested:
                    wrapper = lxml_html.Element("div")
                    wrapper.append(c)
                    _blocks(wrapper, out, depth + 1, list_prefix + "    ")
        elif tag == "pre":
            code = child.text_content().strip("\n")
            if code.strip():
                fence = "`" * max(3, 1 + max((len(m) for m in re.findall(r"`+", code)), default=0))
                lang = next((c[9:] for c in (child.get("class") or "").split() + (child[0].get("class") or "").split()
                             if c.startswith("language-")), "") if len(child) else ""
                out.append(f"{fence}{lang}\n{code}\n{fence}")
        elif tag == "table":
            md = _table(child)
            if md:
                out.append(md)
        elif tag == "hr":
            out.append("---")
        elif tag in BLOCKS or tag in ("li", "td", "th", "tbody", "thead", "tr", "body", "html", "span", "a",
                                      "strong", "b", "em", "i", "code", "small", "label", "time", "abbr"):
            if tag in BLOCKS or tag in ("body", "html", "tbody", "thead", "tr", "td", "th", "li"):
                has_blocks = any(isinstance(c.tag, str) and (c.tag in BLOCKS or c.tag in ("ul", "ol", "pre", "table")
                                 or re.fullmatch(r"h[1-6]", c.tag)) for c in child.iter() if c is not child)
                if has_blocks:
                    _blocks(child, out, depth + 1, list_prefix)
                else:
                    text = _inline(child).strip()
                    if text:
                        out.append(("> " if tag == "blockquote" else "") + text)
            else:
                text = _inline(child).strip()
                if text:
                    out.append(text)
        else:
            text = _inline(child).strip()
            if text:
                out.append(text)
        if child.tail and child.tail.strip():
            out.append(re.sub(r"\s+", " ", child.tail.strip()))


def to_markdown(data: bytes) -> tuple[str, str | None]:
    """(Markdown, page title or None). ValueError when the page has no readable content."""
    try:
        doc = lxml_html.document_fromstring(data)
    except (ValueError, lxml_html.etree.ParserError):
        raise ValueError("the page could not be read") from None
    title_el = doc.find(".//title")
    title = re.sub(r"\s+", " ", title_el.text_content()).strip()[:200] if title_el is not None else None
    root = next((el for el in (doc.find(".//main"), doc.find(".//article"), doc.find(".//body")) if el is not None), doc)
    out: list[str] = []
    _blocks(root, out)
    text = normalize_text("\n\n".join(x for x in out if x.strip()))
    if not text.strip():
        raise ValueError("the page has no readable text (it may need JavaScript)")
    if title and not text.lstrip().startswith("#"):
        text = f"# {title}\n\n{text}"
    return text, title or None
