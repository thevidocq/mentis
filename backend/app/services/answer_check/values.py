"""Level 1: critical values of the answer must be in the passages the model was given.

Contacts and times are what hurts when wrong: phone numbers, e-mail addresses, IP addresses,
clock times, durations, percentages, dates and codes (INC-123456, CVE-2024-1234). They are compared
in a normalised form, so "+39 085 111 2233" matches "085 1112233" and "30 minuti" matches
"30 minutes" or "half an hour" written as "30 min". No model is involved: always on, no cost.
"""

import re
from dataclasses import dataclass

_UNITS = [
    (r"sec(?:ond[io]?s?|s)?|s", 1),
    (r"min(?:ut[eoi]s?|s)?|m(?=\b)", 60),
    (r"h(?:ours?|rs?)?|or[ae]", 3600),
    (r"days?|giorn[oi]|gg", 86400),
    (r"weeks?|settiman[ae]", 604800),
]
_UNIT_RE = "|".join(f"(?:{u})" for u, _ in _UNITS)

PATTERNS = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b")),
    ("date", re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2})\b")),
    ("time", re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")),
    ("duration", re.compile(rf"\b(\d+(?:[.,]\d+)?)\s*({_UNIT_RE})\b", re.I)),
    ("percent", re.compile(r"\b(\d+(?:[.,]\d+)?)\s?%")),
    ("code", re.compile(r"\b[A-Z]{2,10}(?:-\d{2,}){1,3}\b")),
    ("phone", re.compile(r"(?<![\w.])(?:\+|00)?\d[\d ()\-.]{5,}\d(?![\w])")),
]


@dataclass
class Value:
    kind: str
    key: str
    text: str      # as written
    start: int


def _seconds(number: str, unit: str) -> float | None:
    n = float(number.replace(",", "."))
    for pattern, factor in _UNITS:
        if re.fullmatch(pattern, unit, re.I):
            return n * factor
    return None


def extract(text: str) -> list[Value]:
    out: list[Value] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            a, b = m.span()
            if not free(a, b):
                continue
            raw = m.group(0)
            if kind == "email":
                key = raw.lower()
            elif kind == "duration":
                secs = _seconds(m.group(1), m.group(2))
                if secs is None:
                    continue
                key = f"{secs:g}"
            elif kind == "percent":
                key = m.group(1).replace(",", ".")
            elif kind == "date":
                key = re.sub(r"[./-]", "/", raw)
            elif kind == "phone":
                digits = re.sub(r"\D", "", raw)
                if len(digits) < 7 or len(digits) > 15 or re.fullmatch(r"\d{4}", digits):
                    continue
                key = digits[2:] if raw.startswith("00") else digits
            else:
                key = raw.upper() if kind == "code" else raw
            out.append(Value(kind, key, raw.strip(), a))
            taken.append((a, b))
    return out


def _distance(a: str, b: str) -> int:
    """Levenshtein distance (short strings)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _same(a: Value, b: Value) -> bool:
    if a.kind != b.kind:
        return False
    if a.kind == "phone":  # with or without the country prefix
        short, long_ = sorted((a.key, b.key), key=len)
        return long_.endswith(short) and len(short) >= 7
    return a.key == b.key


def check(answer: str, cited: dict[int, str], all_passages: list[str]) -> list[dict]:
    """Issues for values of `answer` that are in none of the passages given to the model.

    `cited`: passage number -> text, for the expected value ("the source says ...") only when the
    sources leave one candidate of the same kind.
    """
    known = [v for p in all_passages for v in extract(p)]
    answer_values = extract(answer)
    issues = []
    for v in answer_values:
        if any(_same(v, k) for k in known):
            continue
        source_values = [k for t in cited.values() for k in extract(t) if k.kind == v.kind]
        unused = [k for k in source_values if not any(_same(k, a) for a in answer_values)]
        keys = {k.key for k in unused}
        issue = {"level": [1], "kind": "value", "text": v.text, "value_kind": v.kind}
        if len(keys) == 1:
            issue["expected"] = unused[0].text
        elif v.kind in ("phone", "email", "ip", "code") and unused:
            # A typo-like difference (5656 vs 5566): the closest value, when clearly the closest.
            ranked = sorted({k.key: k for k in unused}.values(), key=lambda k: _distance(v.key, k.key))
            d = [_distance(v.key, k.key) for k in ranked]
            if d[0] <= 2 and (len(d) == 1 or d[1] > d[0]):
                issue["expected"] = ranked[0].text
        issues.append(issue)
    return issues
