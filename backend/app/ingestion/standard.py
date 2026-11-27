"""Default parser: pdfplumber/pypdfium2 + Tesseract for PDF, python-docx, python-pptx, openpyxl.

Every page/slide/sheet becomes Markdown text with headings and tables preserved.
"""

import io

from PIL import Image

from app.ingestion.images import MAX_IMAGE_PIXELS
from app.ingestion.ocr import ocr_image
from app.ingestion.text import markdown_table, normalize_text
from app.ingestion.types import ExtractedPage, ParseLimits, ParseResult

MIN_NATIVE_CHARS = 25     # below this a PDF page is treated as scanned and OCR'd
OCR_DPI = 300
PREVIEW_DPI = 110


# --- PDF ---------------------------------------------------------------------

# Pixel budget for one rendered page (an A2 page at 300 dpi is about 35 million pixels). A page
# declared far larger (a 200-byte PDF can ask for 14400 x 14400 points) is rendered at a lower
# resolution instead of allocating gigabytes and stalling the worker in OCR.
MAX_RENDER_PIXELS = 40_000_000


def render_scale(width_pt: float, height_pt: float, dpi: int) -> float:
    scale = dpi / 72
    area = max(width_pt, 1.0) * max(height_pt, 1.0) * scale * scale
    return scale if area <= MAX_RENDER_PIXELS else scale * (MAX_RENDER_PIXELS / area) ** 0.5


def _render(pdf, index: int, dpi: int) -> Image.Image:
    page = pdf[index]
    width, height = page.get_size()
    return page.render(scale=render_scale(width, height, dpi)).to_pil()


def _preview(image: Image.Image) -> bytes:
    """Page image for the preview: WebP, about a quarter of the size of a PNG (scans especially)."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="WEBP", quality=80, method=4)
    return buf.getvalue()


IMAGE_MIN_SHARE = 0.05    # an image covering at least this share of a page with text is OCR'd too
SCAN_MAX_TEXT = 200       # a page mostly covered by an image with less text than this is a scan


def _outside(bboxes):
    """pdfplumber filter: objects not inside any of the boxes (table cells are read as tables)."""
    def keep(obj) -> bool:
        x, top = (obj.get("x0", 0) + obj.get("x1", 0)) / 2, (obj.get("top", 0) + obj.get("bottom", 0)) / 2
        return not any(b[0] <= x <= b[2] and b[1] <= top <= b[3] for b in bboxes)
    return keep


def _native(pl) -> tuple[str, int]:
    """The page's text with each table in its place, as a Markdown table, and the table count.
    The text around tables is read without the table cells (they would come twice, flattened)."""
    tables = sorted(pl.find_tables() or [], key=lambda t: t.bbox[1])
    bboxes = [t.bbox for t in tables]
    rest = pl.filter(_outside(bboxes)) if bboxes else pl
    parts, top, count = [], 0.0, 0
    for t in tables:
        x0, t_top, x1, t_bottom = t.bbox
        if t_top > top:
            parts.append(rest.crop((0, top, pl.width, t_top), strict=False).extract_text() or "")
        beside = rest.crop((0, t_top, pl.width, t_bottom), strict=False).extract_text() or ""
        if beside.strip():
            parts.append(beside)
        md = markdown_table(t.extract() or [])
        if md:
            parts.append(md)
            count += 1
        top = max(top, t_bottom)
    if top < pl.height:
        parts.append(rest.crop((0, top, pl.width, pl.height), strict=False).extract_text() or "")
    return normalize_text(("\n\n".join(x.strip() for x in parts if x and x.strip()))), count


def _image_boxes(pl) -> list[tuple[float, float, float, float]]:
    area = max(pl.width * pl.height, 1.0)
    out = []
    for im in pl.images or []:
        x0, top, x1, bottom = max(im["x0"], 0), max(im["top"], 0), min(im["x1"], pl.width), min(im["bottom"], pl.height)
        if x1 > x0 and bottom > top and (x1 - x0) * (bottom - top) / area >= IMAGE_MIN_SHARE:
            out.append((x0, top, x1, bottom))
    return out


def parse_pdf(data: bytes, limits: ParseLimits) -> ParseResult:
    import pdfplumber
    import pypdfium2

    pages: list[ExtractedPage] = []
    warnings: list[str] = []
    pdf = pypdfium2.PdfDocument(data)
    try:
        total = len(pdf)
        if total > limits.max_pages:
            warnings.append(f"Only the first {limits.max_pages} of {total} pages were read.")
        with pdfplumber.open(io.BytesIO(data)) as plumb:
            for i in range(min(total, limits.max_pages)):
                page = ExtractedPage(index=i + 1, kind="page", label=f"Page {i + 1}", text="")
                images: list = []
                try:
                    pl = plumb.pages[i]
                    text, tables = _native(pl)
                    images = _image_boxes(pl)
                except Exception:  # noqa: BLE001 - a malformed page is read with OCR instead
                    text, tables = "", 0
                    warnings.append(f"Page {i + 1}: the text layer could not be read, OCR was used.")
                covered = sum((b[2] - b[0]) * (b[3] - b[1]) for b in images) / max(pl.width * pl.height, 1.0) if images else 0
                if len(text) < MIN_NATIVE_CHARS or (covered >= 0.5 and len(text) < SCAN_MAX_TEXT):
                    # A scan, maybe with a printed footer or a stamp in the text layer: read the
                    # whole page image (the footer is in it too).
                    ocr_text, conf = ocr_image(_render(pdf, i, OCR_DPI), limits.ocr_languages)
                    page.text, page.method, page.ocr_confidence = normalize_text((ocr_text)), "ocr", conf
                    if text and len(page.text) < len(text):
                        page.text, page.method, page.ocr_confidence = text, "native", None
                else:
                    page.text, page.tables = text, tables
                    if images:
                        # Screenshots and diagrams on a text page: their text is read with OCR too.
                        full = _render(pdf, i, OCR_DPI)
                        sx, sy = full.width / pl.width, full.height / pl.height
                        found, confs = [], []
                        for x0, top, x1, bottom in images[:10]:
                            crop = full.crop((int(x0 * sx), int(top * sy), int(x1 * sx), int(bottom * sy)))
                            ocr_text, conf = ocr_image(crop, limits.ocr_languages)
                            if ocr_text.strip():
                                found.append("Text in image:\n" + normalize_text((ocr_text)))
                                if conf is not None:
                                    confs.append(conf)
                        if found:
                            page.text = page.text + "\n\n" + "\n\n".join(found)
                            page.ocr_confidence = min(confs) if confs else None
                page.image = _preview(_render(pdf, i, PREVIEW_DPI))
                pages.append(page.finalize())
    finally:
        pdf.close()
    return ParseResult(pages, warnings)


# --- DOCX --------------------------------------------------------------------

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _local(el) -> str:
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def _run_text(el) -> str:
    """The visible text of a paragraph (or part of one) from its XML: runs, insertions, hyperlinks,
    content controls, fields and smart tags; never deleted text, and text boxes are read apart."""
    out = []
    for node in el.iter():
        name = _local(node)
        if name == "t":
            skip = False
            for a in node.iterancestors():  # up to `el` only: a text box's own paragraphs are read
                if a is el:
                    break
                if _local(a) in ("txbxContent", "del"):
                    skip = True
                    break
            if not skip:
                out.append(node.text or "")
        elif name == "tab":
            out.append("\t")
        elif name in ("br", "cr"):
            out.append("\n")
    return "".join(out)


MAX_BOX_NESTING = 3  # text boxes inside text boxes: deeper ones are not read


def _textboxes(el, budget: "_Budget | None" = None) -> list[str]:
    """Text in text boxes and shapes anchored in a paragraph (each box once: Word stores a copy
    for older readers). Each box reads its own paragraphs only (a box inside it is read as its own
    box), so nested boxes cost no more than their text."""
    seen, out = set(), []
    for box in el.iter(f"{W}txbxContent"):
        if budget is not None and budget.spent:
            break
        if sum(1 for a in box.iterancestors() if _local(a) == "txbxContent") >= MAX_BOX_NESTING:
            continue
        own = [p for p in box.iter(f"{W}p") if next(a for a in p.iterancestors() if _local(a) == "txbxContent") is box]
        text = "\n".join(t for t in (_run_text(p).strip() for p in own) if t)
        if budget is not None:
            text = budget.take(text)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


class _Numbering:
    """List numbers as Word shows them: "1." for numbered levels, "-" for bullets."""

    def __init__(self, doc):
        self.formats: dict[tuple[str, str], str] = {}
        self.counters: dict[tuple[str, str], int] = {}
        try:
            root = doc.part.numbering_part.element
        except Exception:  # noqa: BLE001 - a document without numbering
            return
        abstract = {}
        for a in root.iter(f"{W}abstractNum"):
            abstract[a.get(f"{W}abstractNumId")] = {
                lvl.get(f"{W}ilvl"): (lvl.find(f"{W}numFmt").get(f"{W}val") if lvl.find(f"{W}numFmt") is not None else "bullet")
                for lvl in a.iter(f"{W}lvl")}
        for num in root.iter(f"{W}num"):
            ref = num.find(f"{W}abstractNumId")
            if ref is not None:
                for ilvl, fmt in abstract.get(ref.get(f"{W}val"), {}).items():
                    self.formats[(num.get(f"{W}numId"), ilvl)] = fmt

    def reset_styles(self) -> None:
        """A paragraph that is not a list item ends a list numbered by its style."""
        for k in [k for k in self.counters if k[0] == "style"]:
            del self.counters[k]

    def marker(self, p_el, style: str) -> str:
        num = p_el.find(f"{W}pPr/{W}numPr")
        if num is None:
            if style.startswith("List Number"):
                key = ("style", style)
                self.counters[key] = self.counters.get(key, 0) + 1
                return f"{self.counters[key]}."
            return "-" if style.startswith("List Bullet") else ""
        num_id = num.find(f"{W}numId")
        ilvl = num.find(f"{W}ilvl")
        key = (num_id.get(f"{W}val") if num_id is not None else "0", ilvl.get(f"{W}val") if ilvl is not None else "0")
        if key[0] == "0":
            return ""
        indent = "    " * min(int(key[1]) if key[1].isdigit() else 0, 4)
        if self.formats.get(key, "decimal") in ("bullet", "none"):
            return indent + "-"
        self.counters[key] = self.counters.get(key, 0) + 1
        for deeper in [k for k in self.counters if k[0] == key[0] and k[1] > key[1]]:
            del self.counters[deeper]  # a new item restarts its sub-list
        return f"{indent}{self.counters[key]}."


MAX_TABLE_ROWS = 5000      # rows read per table (the rest is reported)
MAX_NESTING = 5            # tables inside tables read as tables; deeper ones as plain text
MAX_COPY = 200             # a merged cell's value is repeated in the slots it covers only when short
MAX_DOC_CHARS = 5_000_000  # text produced from one Word file: a small crafted file cannot make gigabytes


class _Budget:
    """Characters still allowed for one document; `spent` once it ran out."""

    def __init__(self, chars: int = MAX_DOC_CHARS):
        self.left = chars
        self.spent = False

    def take(self, text: str) -> str:
        if self.spent:
            return ""
        if len(text) > self.left:
            self.spent = True
            text = text[: max(self.left, 0)]
        self.left -= len(text)
        return text


def _own_rows(tbl) -> list:
    """A table's own rows (also those wrapped in a content control), never a nested table's."""
    rows = []
    for child in tbl:
        name = _local(child)
        if name == "tr":
            rows.append(child)
        elif name == "sdt":
            content = child.find(f"{W}sdtContent")
            if content is not None:
                rows.extend(c for c in content if _local(c) == "tr")
    return rows


def _span(tc) -> int:
    span = tc.find(f"{W}tcPr/{W}gridSpan")
    value = span.get(f"{W}val") if span is not None else None
    return min(int(value), 50) if value and value.isdigit() and int(value) > 0 else 1


def _cell_text(tc, budget: _Budget, depth: int = 0) -> str:
    """A table cell: its paragraphs, and the rows of a table nested in it (each nested table read
    once; past MAX_NESTING levels, as plain text)."""
    parts = []
    for child in tc:
        if budget.spent:
            break
        name = _local(child)
        if name == "p":
            t = budget.take(_run_text(child).strip())
            if t:
                parts.append(t)
        elif name == "tbl":
            if depth >= MAX_NESTING:
                t = budget.take(" ".join(_run_text(child).split()))
                if t:
                    parts.append(t)
                continue
            for tr in _own_rows(child)[:MAX_TABLE_ROWS]:
                cells = [_cell_text(c, budget, depth + 1) for c in tr if _local(c) == "tc"]
                if any(cells):
                    parts.append(" | ".join(c for c in cells if c))
        elif name == "sdt":
            content = child.find(f"{W}sdtContent")
            parts.append(_cell_text(content if content is not None else child, budget, depth))
    return "; ".join(p for p in parts if p)


def _docx_table(tbl, budget: _Budget) -> str:
    rows: list[list[str]] = []
    trs = _own_rows(tbl)
    above: list[str] = []
    for tr in trs[:MAX_TABLE_ROWS]:
        if budget.spent:
            break
        row: list[str] = []
        for tc in [c for c in tr if _local(c) in ("tc", "sdt")]:
            if _local(tc) == "sdt":
                inner = tc.find(f"{W}sdtContent/{W}tc")
                if inner is None:
                    continue
                tc = inner
            n = _span(tc)
            vm = tc.find(f"{W}tcPr/{W}vMerge")
            col = len(row)
            if vm is not None and vm.get(f"{W}val") in (None, "continue"):
                # Merged down from the row above: the value above, when short (a "Tier 2" cell).
                for k in range(n):
                    value = above[col + k] if col + k < len(above) else ""
                    row.append(budget.take(value) if len(value) <= MAX_COPY else "")
                continue
            text = _cell_text(tc, budget)
            row.append(text)
            for _ in range(n - 1):  # spread across columns: repeated only when short
                row.append(budget.take(text) if len(text) <= MAX_COPY else "")
        rows.append(row)
        above = row
    md = markdown_table(rows)
    if len(trs) > MAX_TABLE_ROWS:
        md += f"\n\n*{len(trs) - MAX_TABLE_ROWS} more table rows were not read.*"
    return md


def parse_docx(data: bytes, limits: ParseLimits) -> ParseResult:
    """Word has no fixed pages: content is split into sections at each top-level heading. Text is
    read from the document's XML, so tracked insertions, content controls, fields, text boxes,
    nested tables and list numbers are kept; page headers and footers are read once."""
    import docx
    from docx.text.paragraph import Paragraph

    doc = docx.Document(io.BytesIO(data))
    numbering = _Numbering(doc)
    budget = _Budget()
    sections: list[tuple[str, list[str], int]] = []  # (label, blocks, tables)
    label, blocks, tables = "Beginning", [], 0

    def body_items(parent):
        # Content controls (<w:sdt>) wrap paragraphs and tables in many corporate templates.
        for child in parent.iterchildren():
            tag = _local(child)
            if tag == "sdt":
                for inner in child.iterchildren():
                    if _local(inner) == "sdtContent":
                        yield from body_items(inner)
            else:
                yield child, tag

    for child, tag in body_items(doc.element.body):
        if budget.spent:
            break
        if tag == "p":
            p = Paragraph(child, doc)
            text = budget.take(_run_text(child).strip())
            boxes = _textboxes(child, budget)
            style = (p.style.name if p.style is not None else "") or ""
            if text:
                level = int(style.split()[-1]) if style.startswith("Heading") and style.split()[-1].isdigit() else 0
                if style == "Title":
                    level = 1
                if level == 1 and (blocks or sections):
                    sections.append((label, blocks, tables))
                    label, blocks, tables = text[:110], [], 0
                elif level == 1:
                    label = text[:110]
                marker = "" if level else numbering.marker(child, style)
                if not marker:
                    numbering.reset_styles()
                blocks.append(("#" * min(level, 3) + " " + text) if level else (f"{marker} {text}" if marker else text))
            blocks += [b for b in boxes if b]
        elif tag == "tbl":
            md = _docx_table(child, budget)
            if md:
                blocks.append(md)
                tables += 1
    sections.append((label, blocks, tables))

    # Page headers and footers (hotlines, classification, version): once, in the first section.
    extra, seen = [], set()
    for sec in doc.sections:
        for part, name in ((sec.header, "Page header"), (sec.footer, "Page footer")):
            try:
                if part.is_linked_to_previous and seen:
                    continue
                el = part._element
            except Exception:  # noqa: BLE001 - a section without its own header
                continue
            text = "\n".join(t for t in (_run_text(x).strip() for x in el.iter(f"{W}p")) if t)
            if text and text not in seen:
                seen.add(text)
                extra.append(f"{name}: {text}")
    if extra:
        first = sections[0]
        sections[0] = (first[0], first[1] + extra, first[2])

    warnings = ["The document is longer than the size limit: the rest was not read."] if budget.spent else []
    pages = [
        ExtractedPage(index=i + 1, kind="section", label=lbl, text=normalize_text("\n\n".join(b)), tables=t).finalize()
        for i, (lbl, b, t) in enumerate(sections[: limits.max_pages])
        if b or i == 0
    ]
    for i, p in enumerate(pages):
        p.index = i + 1
    return ParseResult(pages, warnings)


# --- PPTX --------------------------------------------------------------------

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _slide_text(frame) -> str:
    """A text frame as list items: auto-numbered paragraphs as "1.", "2." (per level), the others as
    bullets, indented by level, so "step 2" stays step 2."""
    lines, counters = [], {}
    for para in frame.paragraphs:
        text = "".join(r.text for r in para.runs).strip() or (para.text or "").strip()
        if not text:
            continue
        level = min(para.level or 0, 4)
        ppr = para._p.find(f"{_A}pPr")
        auto = ppr is not None and ppr.find(f"{_A}buAutoNum") is not None
        for deeper in [k for k in counters if k > level]:
            del counters[deeper]
        if auto:
            start = ppr.find(f"{_A}buAutoNum").get("startAt")
            counters[level] = counters.get(level, (int(start) - 1) if (start or "").isdigit() else 0) + 1
            marker = f"{counters[level]}."
        else:
            counters.pop(level, None)
            marker = "-"
        lines.append(f"{'    ' * level}{marker} {text}")
    return "\n".join(lines)


def parse_pptx(data: bytes, limits: ParseLimits) -> ParseResult:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(io.BytesIO(data))
    pages: list[ExtractedPage] = []
    for i, slide in enumerate(list(prs.slides)[: limits.max_pages]):
        title = slide.shapes.title.text.strip() if slide.shapes.title is not None and slide.shapes.title.has_text_frame else ""
        page = ExtractedPage(index=i + 1, kind="slide", label=f"Slide {i + 1}" + (f": {title[:90]}" if title else ""), text="")
        blocks = [f"# {title}"] if title else []
        confidences = []

        def flat(shapes):
            # Grouped shapes (diagrams, callouts) keep their text inside the group.
            for sh in shapes:
                if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                    yield from flat(sh.shapes)
                else:
                    yield sh

        for shape in flat(slide.shapes):
            if shape == slide.shapes.title:
                continue
            if shape.has_text_frame and shape.text_frame.text.strip():
                blocks.append(_slide_text(shape.text_frame))
            elif getattr(shape, "has_table", False) and shape.has_table:
                md = markdown_table([[cell.text for cell in row.cells] for row in shape.table.rows])
                if md:
                    blocks.append(md)
                    page.tables += 1
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE or hasattr(shape, "image"):
                # Free pictures and pictures in a placeholder (PlaceholderPicture) alike.
                # Screenshots and diagrams often carry procedure text: read it with OCR.
                try:
                    img = Image.open(io.BytesIO(shape.image.blob))  # header only: nothing decoded yet
                    if img.width * img.height > MAX_IMAGE_PIXELS:
                        continue  # a picture this large is not decoded (a decompression bomb)
                    text, conf = ocr_image(img, limits.ocr_languages)
                except Exception:  # noqa: BLE001 - unreadable images are skipped
                    continue
                if text.strip():
                    blocks.append("Text in image:\n" + text.strip())
                    if conf is not None:
                        confidences.append(conf)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            blocks.append("Speaker notes: " + slide.notes_slide.notes_text_frame.text.strip())
        page.text = normalize_text("\n\n".join(blocks))
        if confidences:
            page.method = "ocr" if not title and len(blocks) == len(confidences) else "native"
            page.ocr_confidence = min(confidences)
        pages.append(page.finalize())
    return ParseResult(pages)


# --- XLSX --------------------------------------------------------------------

def _cell_value(cell):
    """A cell as Excel shows it: percentages as "25%", dates without a midnight time, numbers
    without a trailing ".0"."""
    import datetime

    v = cell.value
    if v is None:
        return None
    fmt = (cell.number_format or "").lower()
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)) and "%" in fmt:
        return f"{v * 100:.10g}%"
    if isinstance(v, datetime.datetime):
        return v.date().isoformat() if v.time() == datetime.time(0, 0) else v.isoformat(sep=" ", timespec="minutes")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return v


def parse_xlsx(data: bytes, limits: ParseLimits) -> ParseResult:
    """Each sheet becomes one Markdown table; values as shown, not formulas. A merged range gives its
    value to every cell it covers ("Tier 2" over two rows is the tier of both)."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), data_only=True)
    pages: list[ExtractedPage] = []
    warnings: list[str] = []
    for i, ws in enumerate(wb.worksheets[: limits.max_pages]):
        page = ExtractedPage(index=i + 1, kind="sheet", label=f"Sheet {ws.title}"[:120], text="")
        if ws.sheet_state != "visible":
            page.flags.append("hidden_sheet")
        merged = list(ws.merged_cells.ranges)
        rows = []
        for r, row in enumerate(ws.iter_rows()):
            if r >= limits.max_sheet_rows:
                page.flags.append("truncated")
                warnings.append(f"Sheet {ws.title}: only the first {limits.max_sheet_rows} rows were read.")
                break
            rows.append([_cell_value(c) for c in row])
        origin_row = origin_col = 1  # iter_rows() starts at A1
        caption = ""
        for rng in merged:
            top = rng.min_row - origin_row
            left = rng.min_col - origin_col
            if top < 0 or left < 0 or top >= len(rows):
                continue
            value = rows[top][left] if left < len(rows[top]) else None
            # A title merged across the first row ("Escalation matrix" over A1:C1) is a caption.
            if top == 0 and rng.max_row == rng.min_row and rng.max_col > rng.min_col \
                    and sum(1 for c in rows[0] if c not in (None, "")) == 1:
                caption = str(value) if value not in (None, "") else caption
                continue
            for rr in range(top, min(rng.max_row - origin_row + 1, len(rows))):
                for cc in range(left, rng.max_col - origin_col + 1):
                    if cc < len(rows[rr]) and (rr, cc) != (top, left):
                        rows[rr][cc] = value
        filled = lambda row: sum(1 for c in row if c not in (None, ""))  # noqa: E731
        if not caption and len(rows) > 1 and filled(rows[0]) == 1 and filled(rows[1]) >= 2:
            # A lone title above a wider table ("Primary SOC hotline" over Name | Phone), merged or not.
            caption = str(next(c for c in rows[0] if c not in (None, "")))
        if caption:
            rows = rows[1:]
        md = markdown_table(rows)
        page.text = normalize_text((f"## {caption}\n\n" if caption else "") + md)
        page.tables = 1 if md else 0
        if merged:
            page.flags.append("merged_cells")
        pages.append(page.finalize())
    return ParseResult(pages, warnings)


def _text_parsers():
    from app.ingestion.datafiles import parse_csv, parse_tsv, parse_yaml
    from app.ingestion.images import parse_image
    from app.ingestion.textfiles import parse_json, parse_md

    return {"md": parse_md, "json": parse_json, "csv": parse_csv, "tsv": parse_tsv, "yaml": parse_yaml,
            "png": parse_image, "jpg": parse_image}


PARSERS = {"pdf": parse_pdf, "docx": parse_docx, "pptx": parse_pptx, "xlsx": parse_xlsx, **_text_parsers()}


def parse(data: bytes, file_type: str, limits: ParseLimits) -> ParseResult:
    return PARSERS[file_type](data, limits)
