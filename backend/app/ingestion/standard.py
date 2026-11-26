"""Default parser: pdfplumber/pypdfium2 + Tesseract for PDF, python-docx, python-pptx, openpyxl.

Every page/slide/sheet becomes Markdown text with headings and tables preserved.
"""

import io

from PIL import Image

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
                table_md = []
                try:
                    pl = plumb.pages[i]
                    for t in pl.extract_tables() or []:
                        md = markdown_table(t)
                        if md:
                            table_md.append(md)
                    text = normalize_text(pl.extract_text() or "")
                except Exception:  # noqa: BLE001 - a malformed page is read with OCR instead
                    text, table_md = "", []
                    warnings.append(f"Page {i + 1}: the text layer could not be read, OCR was used.")
                if len(text) >= MIN_NATIVE_CHARS:
                    page.text = text + ("\n\n" + "\n\n".join(table_md) if table_md else "")
                    page.tables = len(table_md)
                else:
                    ocr_text, conf = ocr_image(_render(pdf, i, OCR_DPI), limits.ocr_languages)
                    page.text, page.method, page.ocr_confidence = normalize_text(ocr_text), "ocr", conf
                page.image = _preview(_render(pdf, i, PREVIEW_DPI))
                pages.append(page.finalize())
    finally:
        pdf.close()
    return ParseResult(pages, warnings)


# --- DOCX --------------------------------------------------------------------

def parse_docx(data: bytes, limits: ParseLimits) -> ParseResult:
    """Word has no fixed pages: content is split into sections at each top-level heading."""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = docx.Document(io.BytesIO(data))
    sections: list[tuple[str, list[str], int]] = []  # (label, blocks, tables)
    label, blocks, tables = "Beginning", [], 0

    def body_items(parent):
        # Content controls (<w:sdt>) wrap paragraphs and tables in many corporate templates.
        for child in parent.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "sdt":
                for inner in child.iterchildren():
                    if inner.tag.rsplit("}", 1)[-1] == "sdtContent":
                        yield from body_items(inner)
            else:
                yield child, tag

    for child, tag in body_items(doc.element.body):
        if tag == "p":
            p = Paragraph(child, doc)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            level = int(style.split()[-1]) if style.startswith("Heading") and style.split()[-1].isdigit() else 0
            if style == "Title":
                level = 1
            if level == 1 and (blocks or sections):
                sections.append((label, blocks, tables))
                label, blocks, tables = text[:110], [], 0
            elif level == 1:
                label = text[:110]
            blocks.append(("#" * min(level, 3) + " " + text) if level else text)
        elif tag == "tbl":
            md = markdown_table([[cell.text for cell in row.cells] for row in Table(child, doc).rows])
            if md:
                blocks.append(md)
                tables += 1
    sections.append((label, blocks, tables))

    pages = [
        ExtractedPage(index=i + 1, kind="section", label=lbl, text=normalize_text("\n\n".join(b)), tables=t).finalize()
        for i, (lbl, b, t) in enumerate(sections[: limits.max_pages])
        if b or i == 0
    ]
    for i, p in enumerate(pages):
        p.index = i + 1
    return ParseResult(pages)


# --- PPTX --------------------------------------------------------------------

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
                blocks.append("\n".join(f"- {line.strip()}" for line in shape.text_frame.text.splitlines() if line.strip()))
            elif getattr(shape, "has_table", False) and shape.has_table:
                md = markdown_table([[cell.text for cell in row.cells] for row in shape.table.rows])
                if md:
                    blocks.append(md)
                    page.tables += 1
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                # Screenshots and diagrams often carry procedure text: read it with OCR.
                try:
                    img = Image.open(io.BytesIO(shape.image.blob))
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

def parse_xlsx(data: bytes, limits: ParseLimits) -> ParseResult:
    """Each sheet becomes one Markdown table; values, not formulas."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), data_only=True)
    pages: list[ExtractedPage] = []
    warnings: list[str] = []
    for i, ws in enumerate(wb.worksheets[: limits.max_pages]):
        page = ExtractedPage(index=i + 1, kind="sheet", label=f"Sheet {ws.title}"[:120], text="")
        merged = list(ws.merged_cells.ranges)
        rows = []
        for r, row in enumerate(ws.iter_rows(values_only=True)):
            if r >= limits.max_sheet_rows:
                page.flags.append("truncated")
                warnings.append(f"Sheet {ws.title}: only the first {limits.max_sheet_rows} rows were read.")
                break
            rows.append(list(row))
        # A merged title row (e.g. "Escalation matrix" across A1:C1) is a caption, not the header.
        caption = ""
        if rows and merged and sum(1 for c in rows[0] if c not in (None, "")) == 1:
            caption = str(next(c for c in rows[0] if c not in (None, "")))
            rows = rows[1:]
        md = markdown_table(rows)
        page.text = normalize_text((f"## {caption}\n\n" if caption else "") + md)
        page.tables = 1 if md else 0
        if merged:
            page.flags.append("merged_cells")
        pages.append(page.finalize())
    return ParseResult(pages, warnings)


PARSERS = {"pdf": parse_pdf, "docx": parse_docx, "pptx": parse_pptx, "xlsx": parse_xlsx}


def parse(data: bytes, file_type: str, limits: ParseLimits) -> ParseResult:
    return PARSERS[file_type](data, limits)
