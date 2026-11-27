"""Small helpers to produce clean Markdown from extracted content."""

import re


def clean_cell(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    return re.sub(r"\s+", " ", text).strip()


MAX_COLUMNS = 200       # columns kept per table
MAX_CELLS = 1_000_000   # cells written per table (rows beyond are reported)


def markdown_table(rows: list[list]) -> str:
    """Rows to a Markdown table; the first non-empty row is the header.

    Bounded: columns empty in every row are dropped before any padding (Excel cells formatted but
    never filled, often up to column XFD, or a crafted row of thousands of empty spanning cells),
    at most MAX_COLUMNS columns and MAX_CELLS cells are written."""
    rows = [[clean_cell(c) for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    keep = sorted({i for r in rows for i, c in enumerate(r) if c})[:MAX_COLUMNS]
    width = len(keep)
    more = max(len(rows) - max(MAX_CELLS // max(width, 1), 2), 0)
    if more:
        rows = rows[: len(rows) - more]
    rows = [[r[i] if i < len(r) else "" for i in keep] for r in rows]
    head, body = rows[0], rows[1:]
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    if more:
        lines.append(f"\n*{more} more table rows were not read (size limit).*")
    return "\n".join(lines)


_INVISIBLE = re.compile(r"[\u00ad\u200b-\u200d\u2060\ufeff]")  # soft hyphen, zero-width characters
def normalize_text(text: str) -> str:
    text = _INVISIBLE.sub("", text.replace("\r", ""))
    text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))  # linear: no regex backtracking
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --- Fenced code blocks (CommonMark) ------------------------------------------------------------

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def fence_open(line: str) -> str | None:
    """The fence (e.g. "```") a line opens, or None. A backtick fence has no backtick in its info."""
    m = _FENCE_OPEN.match(line)
    if not m or (m.group(1)[0] == "`" and "`" in m.group(2)):
        return None
    return m.group(1)


def fence_closes(line: str, fence: str) -> bool:
    """Whether a line closes `fence`: the same character, at least as long, nothing after it."""
    m = re.match(r"^ {0,3}(`{3,}|~{3,})\s*$", line)
    return bool(m) and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)


def fenced_lines(lines: list[str]) -> list[bool]:
    """For each line, whether it is part of a fenced code block (fence lines included)."""
    out, fence = [], None
    for line in lines:
        if fence is None:
            fence = fence_open(line)
            out.append(fence is not None)
        else:
            out.append(True)
            if fence_closes(line, fence):
                fence = None
    return out
