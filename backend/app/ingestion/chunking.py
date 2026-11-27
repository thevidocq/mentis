"""Split extracted pages into retrieval chunks.

Rules: chunks never cross a page/slide/sheet (citations stay exact); tables are kept whole
when they fit, otherwise split by rows with the header repeated; fenced code blocks (YAML rules,
scripts) are kept whole when they fit, otherwise split by lines with the fence repeated, and a
`#` line inside them is never a heading; each chunk remembers the nearest heading so answers can
name the section.
"""

import re
from dataclasses import dataclass

from app.ingestion.text import fenced_lines
from app.ingestion.types import ExtractedPage

TARGET_CHARS = 1500
MAX_CHARS = 2400


@dataclass
class ChunkDraft:
    page_index: int
    heading: str | None
    text: str


def _blocks(text: str) -> list[str]:
    """Paragraphs split at blank lines; a fenced code block stays one block, blank lines included."""
    lines = text.split("\n")
    blocks, current = [], []
    for line, code in zip(lines, fenced_lines(lines)):
        if not code and not line.strip():
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        if code and current and not fenced_lines(current)[-1] and fenced_lines([line])[0]:
            blocks.append("\n".join(current).strip())  # a fence starts a new block
            current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def _is_code(block: str) -> bool:
    return fenced_lines(block.split("\n", 1)[:1])[0]


def _split_code(block: str) -> list[str]:
    """A long code block split by lines, each piece wrapped in the same fence."""
    lines = block.split("\n")
    opening = lines[0]
    closing = lines[-1] if len(lines) > 1 and lines[-1].strip() and set(lines[-1].strip()) <= {"`", "~"} else None
    body = lines[1:-1] if closing else lines[1:]
    fence = re.match(r"^ {0,3}(`{3,}|~{3,})", opening).group(1)
    budget = MAX_CHARS - len(opening) - len(fence) - 2
    parts, current = [], []
    for line in body:
        for piece in ([line] if len(line) <= budget else _split_long(line, max(budget, 200))):
            if current and len("\n".join(current)) + len(piece) + 1 > budget:
                parts.append("\n".join([opening, *current, fence]))
                current = []
            current.append(piece)
    if current or not parts:
        parts.append("\n".join([opening, *current, fence]))
    return parts


def _is_table(block: str) -> bool:
    lines = block.splitlines()
    return len(lines) >= 2 and lines[0].startswith("|") and lines[1].startswith("| ---")


def _split_table(block: str) -> list[str]:
    lines = block.splitlines()
    head, rows = lines[:2], lines[2:]
    parts, current = [], []
    budget = MAX_CHARS - len("\n".join(head)) - 1
    for row in rows:
        if len(row) > budget:  # one huge row (a long Excel cell): split its text, keep the header
            if current:
                parts.append("\n".join(head + current))
                current = []
            parts.extend("\n".join(head + [piece]) for piece in _split_long(row, max(budget, 200)))
            continue
        if current and len("\n".join(head + current + [row])) > MAX_CHARS:
            parts.append("\n".join(head + current))
            current = []
        current.append(row)
    if current:
        parts.append("\n".join(head + current))
    return parts


def _split_long(block: str, limit: int = MAX_CHARS) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", block)
    target = min(TARGET_CHARS, limit)
    parts, current = [], ""
    for s in sentences:
        if len(s) > limit:  # a single huge "sentence": hard cut
            cut = len(s) - len(s) % limit if len(s) % limit else len(s) - limit
            parts.extend(s[i: i + limit] for i in range(0, cut, limit))
            s = s[cut:]
        if current and len(current) + len(s) + 1 > target:
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
            code = _is_code(block)
            if not code and re.match(r"^#{1,6}\s+\S", block):
                flush()
                heading = block.split("\n", 1)[0].lstrip("#").strip()[:300]
                buffer_heading = heading
            if len(block) <= MAX_CHARS:
                pieces = [block]
            elif code:
                pieces = _split_code(block)
            else:
                pieces = _split_table(block) if _is_table(block) else _split_long(block)
            for piece in pieces:
                if buffer and len("\n\n".join(buffer)) + len(piece) > TARGET_CHARS:
                    flush()
                    buffer_heading = heading
                buffer.append(piece)
        flush()
    return chunks
