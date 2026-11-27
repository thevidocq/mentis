"""Split extracted pages into retrieval chunks.

Rules: chunks never cross a page/slide/sheet (citations stay exact); tables are kept whole
when they fit, otherwise split between rows with the header repeated (any Markdown separator row,
and a table that starts right under a caption line); fenced code blocks (YAML rules, scripts) are
kept whole when they fit, otherwise split by lines with the fence repeated, and a `#` line inside
them is never a heading; long text is split at line ends, then sentences, and cut only at a space,
so a name never leaves its phone number. Each chunk remembers its section path ("Ransomware >
Tier 2 > Contacts"), and a heading or a short lead-in ("Call in this order:") is never a chunk on
its own: it goes with what follows.
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


_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
LEAD = 300  # a block this short before a table or a section is kept with it


def _is_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_table(block: str) -> bool:
    lines = block.splitlines()
    return len(lines) >= 2 and _is_row(lines[0]) and bool(_SEPARATOR.match(lines[1]))


def _split_tables_out(block: str) -> list[str]:
    """A block holding a caption and a table (or a table and a note) as separate blocks."""
    lines = block.split("\n")
    out, current, in_table = [], [], False
    for i, line in enumerate(lines):
        starts = _is_row(line) and i + 1 < len(lines) and bool(_SEPARATOR.match(lines[i + 1]))
        if starts and current and not in_table:
            out.append("\n".join(current))
            current = []
        elif in_table and not _is_row(line) and current:
            out.append("\n".join(current))
            current = []
        in_table = starts or (in_table and _is_row(line))
        current.append(line)
    if current:
        out.append("\n".join(current))
    return [b.strip() for b in out if b.strip()]


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


def _hard_cut(text: str, limit: int) -> list[str]:
    """Pieces of at most `limit` characters, cut at the last space before the limit when there is one."""
    parts = []
    while len(text) > limit:
        cut = text.rfind(" ", limit // 2, limit + 1)
        cut = cut if cut > 0 else limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


def _split_long(block: str, limit: int = MAX_CHARS) -> list[str]:
    """Long text in pieces near TARGET_CHARS: at line ends first (PDF text has one line per row of a
    contact list), then at sentence ends, then at a space; never inside a word or a number."""
    target = min(TARGET_CHARS, limit)
    units: list[str] = []
    for line in block.split("\n"):
        if len(line) <= limit:
            units.append(line)
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            units.extend([sentence] if len(sentence) <= limit else _hard_cut(sentence, limit))
    parts, current = [], ""
    for u in units:
        if current and len(current) + len(u) + 1 > target:
            parts.append(current)
            current = u
        else:
            current = f"{current}\n{u}" if current else u
    if current:
        parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def _level(block: str) -> int:
    return len(block) - len(block.lstrip("#"))


def chunk_pages(pages: list[ExtractedPage]) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    for page in pages:
        base = [page.label] if page.kind in ("slide", "sheet") and page.label else []
        stack: list[tuple[int, str]] = []  # open headings: (level, text)
        buffer: list[str] = []
        buffer_path: str | None = None

        def path() -> str | None:
            names = base + [t for _, t in stack]
            return " > ".join(names)[:300] if names else None

        def flush():
            nonlocal buffer
            if buffer:
                chunks.append(ChunkDraft(page.index, buffer_path, "\n\n".join(buffer)))
                buffer = []

        def small() -> bool:
            # Only headings, maybe ending with a short lead-in ("Call in this order:"): they go with
            # what follows instead of becoming a chunk of their own.
            heads = [b for b in buffer if re.match(r"^#{1,6}\s+\S", b) and "\n" not in b]
            rest = buffer[len(heads):] if buffer[:len(heads)] == heads else None
            return rest is not None and (not rest or (len(rest) == 1 and len(rest[0]) <= LEAD
                                                      and rest[0].rstrip().endswith(":")))

        blocks = [b for block in _blocks(page.text) for b in ([block] if _is_code(block) else _split_tables_out(block))]
        for block in blocks:
            code = _is_code(block)
            if not code and re.match(r"^#{1,6}\s+\S", block):
                if not small():
                    flush()
                level = _level(block)
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, block.split("\n", 1)[0].lstrip("#").strip()[:200]))
                if not buffer or small():
                    buffer_path = path()
            elif not buffer:
                buffer_path = path()
            if len(block) <= MAX_CHARS:
                pieces = [block]
            elif code:
                pieces = _split_code(block)
            else:
                pieces = _split_table(block) if _is_table(block) else _split_long(block)
            for piece in pieces:
                if buffer and len("\n\n".join(buffer)) + len(piece) > TARGET_CHARS and not small():
                    flush()
                    buffer_path = path()
                buffer.append(piece)
        flush()
    return chunks
