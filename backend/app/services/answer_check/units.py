"""Statements of an answer: the units both checks work on.

A unit is a line of the answer (a list item, a paragraph line) split at sentence ends. Each keeps
its raw Markdown (to find it again in the text for highlighting) and the passage numbers it cites.

A list item without a citation takes the citations of its parent: the item it is nested under, the
heading above it, or the line introducing the list ("The procedure is [2]:"). So "2. True positive [2]"
followed by three bullets cites [2] for each bullet, and both checks verify them against passage 2.
A line with nested items under it is a heading (intro), not a statement to cite.
"""

import re
from dataclasses import dataclass, field

_CITE = re.compile(r"\[(\d{1,3})\]")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+")
_BOLD_LINE = re.compile(r"^\*\*[^*]+\*\*\s*(?:\[\d{1,3}\]\s*)*:?\s*$")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ*\"“(])")


@dataclass
class Unit:
    raw: str                 # Markdown as in the answer, citations removed from the end
    cites: list[int] = field(default_factory=list)
    intro: bool = False      # ends with ":" ("For Acme:", "The procedure is:") or heads nested items
    inherited: bool = False  # cites are its parent's (a list item under a cited item or heading)
    scope: list[int] = field(default_factory=list)  # an uncited intro: the passages its items cite

    @property
    def plain(self) -> str:
        return plain(self.raw)


def plain(md: str) -> str:
    text = _CITE.sub("", md)
    text = re.sub(r"[*_`]", "", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class _Line:
    text: str        # without list marker, stripped
    indent: int
    kind: str        # "heading" | "numbered" | "bullet" | "para" | "skip"
    cites: list[int]


_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def _lines(answer: str) -> list[_Line]:
    out = []
    fence = None  # the fence of the code block we are in: its lines are code, not statements
    for line in answer.splitlines():
        if not line.strip():
            continue
        m = _FENCE.match(line)
        if fence is not None or m:
            if fence is None:
                fence = m.group(1)
            elif m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)):].strip():
                fence = None
            out.append(_Line(line.strip(), 0, "skip", []))
            continue
        indent = len(line) - len(line.lstrip())
        text = _LIST.sub("", line).strip()
        if _LIST.match(line):
            kind = "numbered" if _NUMBERED.match(line) else "bullet"
        elif text.startswith("#") or _BOLD_LINE.match(text):
            kind = "heading"
        elif text.startswith(("|", "```")):
            kind = "skip"
        else:
            kind = "para"
        out.append(_Line(text, indent, kind, [int(n) for n in _CITE.findall(text)]))
    return out


def _parent(lines: list[_Line], i: int) -> int | None:
    """The line a list item hangs from, if any: a less indented item (or a numbered item above a
    bullet at the same indent), the heading above, or a lead line ending with ":"."""
    cur = lines[i]
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
        if r.kind == "skip":
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


def table_rows(answer: str) -> list[tuple[str, list[int]]]:
    """Table rows outside code blocks (not the |---| separator), with their citations."""
    return [(line.text, line.cites) for line in _lines(answer)
            if line.kind == "skip" and line.text.startswith("|") and not re.fullmatch(r"[|:\s-]+", line.text)]


def split(answer: str) -> list[Unit]:
    lines = _lines(answer)
    parents = [_parent(lines, i) for i in range(len(lines))]
    heads = {p for p in parents if p is not None}
    effective: list[list[int]] = []  # each line's own citations, or its parent's
    for i, line in enumerate(lines):
        p = parents[i]
        effective.append(line.cites or (effective[p] if p is not None else []))
    below: dict[int, set[int]] = {}  # a head line: the passages its items cite (checked in its place)
    for i, p in enumerate(parents):
        if p is not None:
            below.setdefault(p, set()).update(effective[i])
    units: list[Unit] = []
    for i, line in enumerate(lines):
        if line.kind == "skip" or line.text.startswith("#") and not line.cites:
            continue
        own_line = bool(line.cites)
        for part in _SENT.split(line.text):
            cites = [int(n) for n in _CITE.findall(part)]
            # Up to the first citation or the end, without closing punctuation: the exact text to find
            # again in the answer for highlighting ("informed by SMS [1]." -> "informed by SMS").
            raw = _CITE.split(part)[0] if _CITE.search(part) and not _CITE.sub("", part.split("[", 1)[-1]).strip(" .;:!?") else _CITE.sub("", part)
            intro = (_CITE.sub("", part).rstrip().endswith(":") or (i in heads and not cites)
                     or line.kind == "heading")
            raw = re.sub(r"[\s.;:!?]+$", "", raw.strip())
            inherited = False
            if not cites and not own_line and effective[i] and line.kind in ("numbered", "bullet", "para"):
                cites, inherited = list(effective[i]), True  # the whole line hangs from a cited parent
            if len(plain(raw)) >= 3:
                scope = sorted(below.get(i, ())) if intro and not cites else []
                units.append(Unit(raw=raw, cites=cites, intro=intro, inherited=inherited, scope=scope))
    return units
