"""Statements of an answer: the units both checks work on.

A unit is a line of the answer (a list item, a paragraph line) split at sentence ends. Each keeps
its raw Markdown (to find it again in the text for highlighting) and the passage numbers it cites.
"""

import re
from dataclasses import dataclass, field

_CITE = re.compile(r"\[(\d{1,3})\]")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ*\"“(])")


@dataclass
class Unit:
    raw: str                 # Markdown as in the answer, citations removed from the end
    cites: list[int] = field(default_factory=list)
    intro: bool = False      # ends with ":" ("For Acme:", "The procedure is:"): introduces the next lines

    @property
    def plain(self) -> str:
        return plain(self.raw)


def plain(md: str) -> str:
    text = _CITE.sub("", md)
    text = re.sub(r"[*_`]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split(answer: str) -> list[Unit]:
    units: list[Unit] = []
    for line in answer.splitlines():
        line = _LIST.sub("", line).strip()
        if not line or line.startswith(("|", "#", "```")) and not _CITE.search(line):
            continue
        for part in _SENT.split(line):
            cites = [int(n) for n in _CITE.findall(part)]
            # Up to the first citation or the end, without closing punctuation: the exact text to find
            # again in the answer for highlighting ("informed by SMS [1]." -> "informed by SMS").
            raw = _CITE.split(part)[0] if _CITE.search(part) and not _CITE.sub("", part.split("[", 1)[-1]).strip(" .;:!?") else _CITE.sub("", part)
            intro = _CITE.sub("", part).rstrip().endswith(":")
            raw = re.sub(r"[\s.;:!?]+$", "", raw.strip())
            if len(plain(raw)) >= 3:
                units.append(Unit(raw=raw, cites=cites, intro=intro))
    return units
