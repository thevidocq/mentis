"""Statements of an answer: the units both checks work on.

Every line the analyst sees becomes a unit, so nothing shown escapes the check:
- a paragraph (its lines joined, as the chat shows them) or a list item, split at sentence ends; a
  heading (`#` to `###`, or a bold line standing alone);
- a code block (fenced with three backticks), as one unit: commands are what analysts copy;
- a table row, as one unit (the header row is an introduction).
Blocks are recognised exactly as the chat renders them (components/Markdown.tsx): a code block opens
and closes on a line starting with three backticks; a table row starts and ends with "|". Text the
chat shows as prose (a "~~~" line, an indented fence, "| a" without a closing pipe) is checked as prose.

Each unit keeps its raw Markdown (to find it again in the text for highlighting) and the passage
numbers it cites. A unit without a citation takes the citations of its parent: the item it is nested
under, the heading or lead line above it ("The procedure is [2]:"), or the lead line of a code block
or a table (else the other rows of its table, else every passage the answer cites). A sentence of a
cited line without its own citation stays uncited. A line with items, code or a table under it is an
introduction ("intro"): checked for the facts it states, against the passages its items cite.
"""

import re
from dataclasses import dataclass, field

_CITE = re.compile(r"\[(\d{1,3})\]")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+")
_BOLD_LINE = re.compile(r"^\*\*[^*]+\*\*\s*(?:\[\d{1,3}\]\s*)*:?\s*$")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ*\"“(])")
_ROW = re.compile(r"^\s*\|.*\|\s*$")            # as the chat: starts and ends with a pipe
_SEPARATOR = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")
BLOCKS = ("code", "row", "rowhead", "skip")    # lines that are not prose


@dataclass
class Unit:
    raw: str                 # Markdown as in the answer, citations removed from the end
    cites: list[int] = field(default_factory=list)
    intro: bool = False      # heads nested items, a code block or a table
    inherited: bool = False  # cites are its parent's (a list item under a cited item or heading)
    scope: list[int] = field(default_factory=list)  # an uncited intro: the passages its items cite
    text: str = ""           # the statement as written in the answer, citations inside it kept
    block: str = ""          # "code" | "row" | "" (prose)

    @property
    def plain(self) -> str:
        return self.raw if self.block == "code" else plain(self.raw)


_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_EM_STAR = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])")


def plain(md: str) -> str:
    """The text as the analyst reads it: citations and the Markdown markers the chat renders removed
    (bold, *italic*, inline code), nothing else ("_x_", "svc_backup", "*.exe" and paths keep theirs)."""
    text = re.sub(r"^\s*#{1,6}\s+", "", _CITE.sub("", md))
    text = _BOLD.sub(r"\1", text)
    text = _EM_STAR.sub(r"\1", text)
    text = text.replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class _Line:
    text: str        # without list marker, stripped
    indent: int
    kind: str        # "heading" | "numbered" | "bullet" | "para" | "code" | "row" | "rowhead" | "skip"
    cites: list[int]
    table: int = -1  # the table a row belongs to


_HEADING = re.compile(r"^(#{1,3})\s+\S")                 # the chat's headings: # to ###
_ITEM = re.compile(r"^\s*(?:-|\d+\.)\s+")                 # the chat's list items: "-" and "1."
_PARA_STOP = re.compile(r"^(?:#|>|```|\s*\||\s*(?:-|\d+\.)\s)")  # a line that ends a paragraph


def _lines(answer: str) -> list[_Line]:
    """The answer's blocks as the chat builds them (components/Markdown.tsx): a paragraph joins its
    lines with a space, and so does a ">" note, so "Do not\nisolate the host" is one statement, as
    the analyst reads it; list items, headings, code blocks and table rows are lines of their own."""
    out: list[_Line] = []
    rows = answer.replace("\r", "").split("\n")
    i, table, in_table, head = 0, -1, False, False
    while i < len(rows):
        line = rows[i]
        if not line.strip():
            i += 1
            in_table = False
            continue
        if line.startswith("```"):  # the chat's code block: up to the next line starting with ```
            code = []
            i += 1
            while i < len(rows) and not rows[i].startswith("```"):
                code.append(rows[i])
                i += 1
            i += 1
            body = "\n".join(c.rstrip() for c in code).strip("\n")
            if body.strip():
                out.append(_Line(body, 0, "code", []))
            in_table = False
            continue
        if _ROW.match(line):
            if not in_table:
                table, in_table, head = table + 1, True, True
            i += 1
            if _SEPARATOR.match(line):
                out.append(_Line(line.strip(), 0, "skip", [], table))
                continue
            text = line.strip()
            out.append(_Line(text, 0, "rowhead" if head else "row", [int(n) for n in _CITE.findall(text)], table))
            head = False
            continue
        in_table = False
        if _HEADING.match(line):
            text = line.strip()
            out.append(_Line(text, 0, "heading", [int(n) for n in _CITE.findall(text)]))
            i += 1
            continue
        if line.startswith(">"):
            note = []
            while i < len(rows) and rows[i].startswith(">"):
                note.append(re.sub(r"^>\s?", "", rows[i]))
                i += 1
            text = " ".join(note).strip()
            if text:
                out.append(_Line(text, 0, "para", [int(n) for n in _CITE.findall(text)]))
            continue
        if _ITEM.match(line) or (re.match(r"^ {4}\S", line) and out and out[-1].kind in ("numbered", "bullet")):
            indent = len(line) - len(line.lstrip())
            text = _ITEM.sub("", line).strip()
            kind = "numbered" if _NUMBERED.match(line) else "bullet"
            out.append(_Line(text, indent, kind, [int(n) for n in _CITE.findall(text)]))
            i += 1
            continue
        # A paragraph: this line and the next ones up to a blank line or another block, joined.
        para = [line.strip()]
        i += 1
        while i < len(rows) and rows[i].strip() and not _PARA_STOP.match(rows[i]):
            para.append(rows[i].strip())
            i += 1
        text = " ".join(para)
        kind = "heading" if len(para) == 1 and _BOLD_LINE.match(text) else "para"
        out.append(_Line(text, len(line) - len(line.lstrip()), kind, [int(n) for n in _CITE.findall(text)]))
    return out


def _parent(lines: list[_Line], i: int) -> int | None:
    """The line a unit hangs from, if any: a less indented item (or a numbered item above a bullet
    at the same indent), the heading above, a lead line ending with ":", or, for a code block or a
    table, the prose line right above it."""
    cur = lines[i]
    if cur.kind in ("code", "row", "rowhead", "skip"):
        j = i - 1
        while j >= 0 and cur.table >= 0 and lines[j].table == cur.table:
            j -= 1
        if j < 0 or lines[j].kind in BLOCKS:
            return None
        lead = lines[j]
        # A lead line introduces the block ("Run [1]:", a heading, a cited line); an uncited
        # statement that only happens to stand above it stays a statement of its own.
        if lead.kind == "heading" or lead.cites or _CITE.sub("", lead.text).rstrip().endswith(":"):
            return j
        return None
    for j in range(i - 1, -1, -1):
        r = lines[j]
        if cur.kind == "heading":
            # A heading hangs only from a higher-level "#" heading, never from the previous section.
            if r.kind == "heading" and cur.text.startswith("#") and r.text.startswith("#") \
                    and _level(r.text) < _level(cur.text):
                return j
            continue
        if r.kind == "heading":
            return j
        if r.kind in BLOCKS:
            return None
        if cur.kind == "para":  # a paragraph hangs only from a heading right above it
            return None
        if r.kind == "para":
            return j if _CITE.sub("", r.text).rstrip().endswith(":") and r.indent <= cur.indent else None
        if r.indent < cur.indent or (r.indent == cur.indent and r.kind == "numbered" and cur.kind == "bullet"):
            return j
        # a sibling: keep looking up for the common parent
    return None


def _level(text: str) -> int:
    return len(text) - len(text.lstrip("#"))


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _row_text(line: str, header: list[str] | None = None) -> str:
    """A table row as one statement, each cell with its column name when the header has as many
    cells ("Role: Primary | Contact: Laura Bianchi"): checked in any group, it keeps its meaning."""
    cells = _cells(line)
    if header and len(header) == len(cells):
        return " | ".join(f"{_CITE.sub('', h).strip()}: {c}" if _CITE.sub("", h).strip() else c for h, c in zip(header, cells))
    return " | ".join(cells)


_END = " \t\n\r\f\v.;:!?"


def _trim(text: str) -> str:
    """Without closing punctuation and spaces (str.rstrip: linear, a regex here was quadratic)."""
    return text.strip().rstrip(_END)


def _drop_closing_cites(text: str) -> str:
    """Without the citations that close it ("informed by SMS [1][2]" -> "informed by SMS")."""
    while True:
        m = re.search(r"\[\d{1,3}\]$", text)
        if not m:
            return text
        text = _trim(text[:m.start()])


def split(answer: str) -> list[Unit]:
    lines = _lines(answer)
    parents = [_parent(lines, i) for i in range(len(lines))]
    heads = {p for p in parents if p is not None}
    tables: dict[int, set[int]] = {}  # a table: every passage its rows cite
    for line in lines:
        if line.table >= 0:
            tables.setdefault(line.table, set()).update(line.cites)
    effective: list[list[int]] = []  # each line's own citations, or its parent's
    for i, line in enumerate(lines):
        p = parents[i]
        inherited = effective[p] if p is not None else []
        if line.kind == "row" and not line.cites:
            inherited = sorted(tables.get(line.table, ())) or inherited
        effective.append(line.cites or inherited)
    below: dict[int, set[int]] = {}  # a head line: the passages its items cite (checked in its place)
    for i, p in enumerate(parents):
        if p is not None:
            below.setdefault(p, set()).update(effective[i])
    # Code and table rows citing nothing (not even through their lead line): checked against every
    # passage the answer cites, as their values must come from somewhere the analyst can open.
    answer_cites = sorted({n for line in lines for n in line.cites})
    headers = {line.table: _cells(line.text) for line in lines if line.kind == "rowhead"}
    units: list[Unit] = []
    for i, line in enumerate(lines):
        if line.kind == "skip":
            continue
        if line.kind == "code":
            units.append(Unit(raw=line.text, cites=list(effective[i] or answer_cites), inherited=True, text=line.text, block="code"))
            continue
        if line.kind in ("row", "rowhead"):
            raw = _CITE.sub("", _row_text(line.text, headers.get(line.table) if line.kind == "row" else None)).strip()
            if not re.search(r"[^\W_]", plain(raw)):
                continue
            if line.kind == "rowhead":
                scope = sorted(tables.get(line.table, ()) | set(effective[i])) or answer_cites
                units.append(Unit(raw=raw, cites=list(line.cites), intro=True, scope=[] if line.cites else scope,
                                  text=line.text, block="row"))
            else:
                units.append(Unit(raw=raw, cites=list(effective[i] or answer_cites), inherited=not line.cites, text=line.text, block="row"))
            continue
        parts = _SENT.split(line.text)
        for k, part in enumerate(parts):
            cites = [int(n) for n in _CITE.findall(part)]
            # Up to the first citation or the end, without closing punctuation: the exact text to find
            # again in the answer for highlighting ("informed by SMS [1]." -> "informed by SMS").
            raw = _CITE.split(part)[0] if _CITE.search(part) and not _CITE.sub("", part.split("[", 1)[-1]).strip(" .;:!?") else _CITE.sub("", part)
            # A heading, or the last sentence of a line with items, code or a table under it.
            intro = line.kind == "heading" or (i in heads and k == len(parts) - 1)
            raw = _trim(raw)
            inherited = False
            if not cites and not line.cites and effective[i]:
                # The whole line hangs from a cited parent. A sentence of a cited line without its own
                # citation does not borrow the others': it is uncited (level 2 still reads it).
                cites, inherited = list(effective[i]), True
            if re.search(r"[^\W_]", plain(raw)):  # anything with a letter or digit ("3", "Y")
                scope = sorted(below.get(i, ())) if intro and not cites else []
                # As written (a citation in the middle kept), up to its closing citations: found
                # verbatim in the answer, so the chat can mark a value inside this statement.
                text = _trim(_drop_closing_cites(_trim(part)))
                units.append(Unit(raw=raw, cites=cites, intro=intro,
                                  inherited=inherited, scope=scope, text=text))
    return units
