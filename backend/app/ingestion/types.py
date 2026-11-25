from dataclasses import dataclass, field

LOW_CONFIDENCE = 0.6  # OCR mean word confidence below this is flagged for review


@dataclass
class ParseLimits:
    max_pages: int = 1000
    max_sheet_rows: int = 5000
    ocr_languages: str = "eng+ita"


@dataclass
class ExtractedPage:
    index: int                      # 1-based
    kind: str                       # page | section | slide | sheet
    label: str
    text: str                       # Markdown
    method: str = "native"          # native | ocr
    ocr_confidence: float | None = None
    tables: int = 0
    image: bytes | None = None      # PNG render for the preview (PDF pages)
    flags: list[str] = field(default_factory=list)

    def finalize(self) -> "ExtractedPage":
        if not self.text.strip():
            self.flags.append("empty")
        if self.ocr_confidence is not None and self.ocr_confidence < LOW_CONFIDENCE:
            self.flags.append("low_confidence")
        return self


@dataclass
class ParseResult:
    pages: list[ExtractedPage]
    warnings: list[str] = field(default_factory=list)

    def stats(self) -> dict:
        return {
            "pages": len(self.pages),
            "ocr_pages": sum(p.method == "ocr" for p in self.pages),
            "tables": sum(p.tables for p in self.pages),
            "empty_pages": sum("empty" in p.flags for p in self.pages),
            "low_confidence_pages": sum("low_confidence" in p.flags for p in self.pages),
            "chars": sum(len(p.text) for p in self.pages),
            "warnings": self.warnings,
        }
