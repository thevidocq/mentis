"""Optional Docling parser (MENTIS_PARSER=docling).

NOT VERIFIED IN CI: Docling needs PyTorch and layout models downloaded from HuggingFace,
which the development environment cannot reach. Verify in the lab on real documents before
making it the default. The worker image must be built with the `docling` extra.

Produces the same ExtractedPage structure as the standard parser, so the rest of the
pipeline (preview, chunks, approval) is unchanged.
"""

import io

from app.ingestion.text import normalize_text
from app.ingestion.types import ExtractedPage, ParseLimits, ParseResult

_KIND = {"pdf": ("page", "Page"), "pptx": ("slide", "Slide"), "docx": ("section", "Section"), "xlsx": ("sheet", "Sheet")}


def parse_with_docling(data: bytes, file_type: str, limits: ParseLimits) -> ParseResult:
    from docling.datamodel.base_models import DocumentStream
    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(DocumentStream(name=f"upload.{file_type}", stream=io.BytesIO(data)))
    doc = result.document
    kind, word = _KIND[file_type]
    page_numbers = sorted(doc.pages.keys()) if getattr(doc, "pages", None) else []
    pages: list[ExtractedPage] = []
    warnings: list[str] = []

    if page_numbers:
        if len(page_numbers) > limits.max_pages:
            warnings.append(f"Only the first {limits.max_pages} of {len(page_numbers)} pages were read.")
        for n in page_numbers[: limits.max_pages]:
            text = normalize_text(doc.export_to_markdown(page_no=n))
            tables = sum(1 for t in doc.tables if any(p.page_no == n for p in t.prov))
            pages.append(ExtractedPage(index=n, kind=kind, label=f"{word} {n}", text=text, tables=tables).finalize())
    else:
        text = normalize_text(doc.export_to_markdown())
        pages.append(ExtractedPage(index=1, kind=kind, label=f"{word} 1", text=text, tables=len(doc.tables)).finalize())
    return ParseResult(pages, warnings)
