"""Document parsing: turns an uploaded file into pages of Markdown text plus quality signals."""

from app.ingestion.types import ExtractedPage, ParseLimits, ParseResult


def parse(data: bytes, file_type: str, limits: ParseLimits, parser: str = "standard") -> ParseResult:
    if parser == "docling":
        from app.ingestion.docling_parser import parse_with_docling

        return parse_with_docling(data, file_type, limits)
    from app.ingestion import standard

    return standard.parse(data, file_type, limits)


__all__ = ["ExtractedPage", "ParseLimits", "ParseResult", "parse"]
