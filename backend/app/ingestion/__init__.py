"""Document parsing: turns an uploaded file into pages of Markdown text plus quality signals."""

from app.ingestion.types import ExtractedPage, ParseLimits, ParseResult

DOCLING_TYPES = {"pdf", "docx", "pptx", "xlsx"}  # the others are read as they are by the standard parser


def parse(data: bytes, file_type: str, limits: ParseLimits, parser: str = "standard") -> ParseResult:
    if parser == "docling" and file_type in DOCLING_TYPES:
        from app.ingestion.docling_parser import parse_with_docling

        return parse_with_docling(data, file_type, limits)
    from app.ingestion import standard

    return standard.parse(data, file_type, limits)


__all__ = ["ExtractedPage", "ParseLimits", "ParseResult", "parse"]
