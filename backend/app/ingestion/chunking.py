"""Split extracted pages into retrieval chunks.

Rules: chunks never cross a page/slide/sheet (citations stay exact); tables are kept whole
when they fit, otherwise split by rows with the header repeated; each chunk remembers the
nearest heading so answers can name the section.
"""

import re
from dataclasses import dataclass

from app.ingestion.types import ExtractedPage

TARGET_CHARS = 1500
MAX_CHARS = 2400


@dataclass
class ChunkDraft:
    page_index: int
    heading: str | None
    text: str


def _blocks(text: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]


def _is_table(block: str) -> bool:
    lines = block.splitlines()
    return len(lines) >= 2 and lines[0].startswith("|") and lines[1].startswith("| ---")


def _split_table(block: str) -> list[str]:
    lines = block.splitlines()
    head, rows = lines[:2], lines[2:]
    parts, current = [], []
    for row in rows:
        if current and len("\n".join(head + current + [row])) > MAX_CHARS:
            parts.append("\n".join(head + current))
            current = []
        current.append(row)
    if current:
        parts.append("\n".join(head + current))
    return parts


def _split_long(block: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", block)
    parts, current = [], ""
    for s in sentences:
        while len(s) > MAX_CHARS:  # a single huge "sentence": hard cut
            parts.append(s[:MAX_CHARS])
            s = s[MAX_CHARS:]
        if current and len(current) + len(s) + 1 > TARGET_CHARS:
            parts.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        parts.append(current)
    return parts


def chunk_pages(pages: list[ExtractedPage]) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    for page in pages:
        heading = page.label if page.kind in ("slide", "sheet") else None
        buffer: list[str] = []
        buffer_heading = heading

        def flush():
            nonlocal buffer
            if buffer:
                chunks.append(ChunkDraft(page.index, buffer_heading, "\n\n".join(buffer)))
                buffer = []

        for block in _blocks(page.text):
            if block.startswith("#"):
                flush()
                heading = block.lstrip("#").strip()[:300]
                buffer_heading = heading
            pieces = _split_table(block) if _is_table(block) and len(block) > MAX_CHARS else (
                _split_long(block) if len(block) > MAX_CHARS else [block])
            for piece in pieces:
                if buffer and len("\n\n".join(buffer)) + len(piece) > TARGET_CHARS:
                    flush()
                    buffer_heading = heading
                buffer.append(piece)
        flush()
    return chunks
