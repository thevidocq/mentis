"""Level 1: critical values of the answer must be in the passages the model was given.

Contacts and times are what hurts when wrong: phone numbers, e-mail addresses, IP addresses (with
their port), clock times (24 h, AM/PM, "9.30"), durations, percentages, dates, ticket and
vulnerability codes (INC-123456, INC0012345, CVE-2024-1234, T1059.001) and file hashes. Also MAC
addresses, URLs and domains, Windows paths and registry keys, event IDs, ports, extensions and plain
numbers (a count, a threshold). They are compared in a normalised form, so "+39 085 111 2233" matches
"085 1112233", "9:00 PM" matches "21:00", "90 min" matches "1 hour 30 minutes", "30 minuti" matches
"30 min" and a defanged "10[.]0[.]0[.]1" matches "10.0.0.1". Both texts are normalised first (compatibility forms,
Unicode dashes and spaces, soft hyphens), as the model read them. No model is involved: always on,
no cost. It is a safety net, not a proof: level 2 judges the statements.
"""

import re
import unicodedata
from dataclasses import dataclass

_UNITS = [
    (r"sec(?:ond[io]?s?|s)?|s", 1),
    (r"min(?:ut[eoi]s?|s)?|m(?=\b)", 60),
    (r"h(?:ours?|rs?)?|or[ae]", 3600),
    (r"days?|giorn[oi]|gg", 86400),
    (r"weeks?|settiman[ae]", 604800),
    (r"months?|mes[ei]", 2592000),
    (r"years?|ann[oi]", 31536000),
]
_UNIT_RE = "|".join(f"(?:{u})" for u, _ in _UNITS)
_WORDS = {w: n for n, ws in {
    1: "one uno una un", 2: "two due", 3: "three tre", 4: "four quattro", 5: "five cinque", 6: "six sei",
    7: "seven sette", 8: "eight otto", 9: "nine nove", 10: "ten dieci", 11: "eleven undici", 12: "twelve dodici",
    15: "fifteen quindici", 20: "twenty venti", 24: "twenty-four ventiquattro", 30: "thirty trenta",
    45: "forty-five quarantacinque", 48: "forty-eight quarantotto", 60: "sixty sessanta", 72: "seventy-two settantadue",
}.items() for w in ws.split()}
_WORD_RE = "|".join(sorted(map(re.escape, _WORDS), key=len, reverse=True))
_TLD = ("com|net|org|io|info|biz|gov|edu|mil|int|co|uk|de|it|fr|es|nl|eu|ru|cn|ch|at|be|se|no|dk|fi|pl|pt|cz|"
        "us|ca|au|jp|in|br|xyz|top|online|site|app|dev|cloud|tech|local|corp|lan|internal|onion|arpa")
_CODE_PREFIXES = r"INC|RITM|REQ|CHG|PRB|TASK|SCTASK|SIR|KB|CS|SR|TKT|WO"

PATTERNS = [
    ("url", re.compile(r"\b(?:https?|ftp)://[^\s<>()\[\]\"'`|]+")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("path", re.compile(r"\b(?:HKLM|HKCU|HKCR|HKU|HKCC|HKEY_[A-Z_]+):?\\[^\s\"'<>|]+|\b[A-Za-z]:\\[^\s\"'<>|*?]+"
                        r"|\\\\[\w.$-]+(?:\\[^\s\"'<>|*?]+)+")),
    ("mac", re.compile(r"\b[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}\b")),
    # Any long hex run is a hash or a key: a 63-character "SHA-256" is a wrong one, not a word.
    ("hash", re.compile(r"\b[a-fA-F0-9]{30,130}\b")),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2}|:\d{1,5})?\b")),
    ("ip", re.compile(r"(?<![\w:])(?:[0-9a-fA-F]{1,4}:){1,7}:?(?:[0-9a-fA-F]{1,4})?(?:/\d{1,3})?(?![\w:])")),
    ("code", re.compile(rf"\b(?:[A-Z]{{2,10}}(?:-\d{{2,}}){{1,3}}|(?i:cve|cwe|ghsa)-[\w-]{{4,}}|(?i:{_CODE_PREFIXES})\d{{5,}}"
                        r"|T\d{4}(?:\.\d{3})?)\b")),
    ("domain", re.compile(rf"(?<![@\w.-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]{{0,61}}[A-Za-z0-9])?\.)+(?i:{_TLD})\b(?![.-]?\w)")),
    ("time", re.compile(r"(?<![\d.:])([01]?\d|2[0-3])[:.]([0-5]\d)(?::[0-5]\d)?(?:\s*([AaPp])\.?\s?[Mm]\.?(?![a-z]))?(?![.:]?\d)")),
    ("trange", re.compile(r"(?<![\d.:])(1[0-2]|0?[1-9])\s*[-–]\s*(1[0-2]|0?[1-9])\s*([AaPp])\.?\s?[Mm]\.?(?![a-z])")),
    ("time", re.compile(r"(?<![\d.:])(1[0-2]|0?[1-9])()\s*([AaPp])\.?\s?[Mm]\.?(?![a-z])")),
    ("date", re.compile(r"\b(?:\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2})|\d{4}-\d{2}-\d{2})\b")),
    ("range", re.compile(rf"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:-|to|a|fino a)\s*(\d+(?:[.,]\d+)?)\s*({_UNIT_RE})\b", re.I)),
    ("hm", re.compile(r"(?<![\d.,])(\d{1,3})\s*h\s*(\d{1,2})(?:\s*(?:m|min|minutes?|minuti))?\b", re.I)),
    ("duration", re.compile(rf"(?<![\d.,])(\d+(?:[.,]\d+)?|\b(?:{_WORD_RE}))(?:\s*|-)({_UNIT_RE})\b", re.I)),
    ("percent", re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)(?:\s?%|\s+(?:percent|per\s?cent[oi]?)\b)", re.I)),
    ("event", re.compile(r"\b(?:event\s*id|eventid|event\s*code|id\s+evento|evento)\s*[:#]?\s*(\d{1,6})\b", re.I)),
    ("port", re.compile(r"\b(?:port[ae]?|tcp|udp)\s*[:/#]?\s*(\d{1,5})\b", re.I)),
    ("extension", re.compile(r"\b(?:ext\.?|extension|interno|int\.)\s*[:#]?\s*(\d{2,6})\b", re.I)),
    ("phone", re.compile(r"(?<![\w.])(?:\+|00)?\d[\d ()\-.]{5,}\d(?![\w])")),
    # Any other number (a count, a threshold, a step): it must be in the passages too.
    ("number", re.compile(r"(?<![\w.,:/\\-])\d+(?:[.,]\d+)?(?![\w:/\\]|[.,]\d)")),
]

# Calling codes that can stand before a national number ("+39 085…" = "085…"); anything else in
# front of a number makes it another number.
_COUNTRY = set("1 7 20 27 30 31 32 33 34 36 39 40 41 43 44 45 46 47 48 49 51 52 53 54 55 56 57 58 60 61 62 63 64 "
               "65 66 81 82 84 86 90 91 92 93 94 95 98 212 213 216 351 352 353 354 355 356 357 358 359 370 371 372 "
               "373 374 375 376 377 378 380 381 382 385 386 387 389 420 421 423 852 961 962 965 966 971 972 973 974".split())

# Numbers that look like phones but are not: ranges ("2023-2024", "1000 - 2000") and amounts with
# thousands separators ("1.000.000", "1,250,000", "10 000 000").
_RANGE = re.compile(r"\d+\s*[-–]\s*\d+")
_AMOUNT = re.compile(r"\d{1,3}(?:([.,  ])\d{3})(?:\1\d{3})*")
_SPACES = re.compile(r"[   -   　]")
_DASHES = re.compile(r"[‐-―−﹘﹣－]")
_INVISIBLE = re.compile(r"[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
_FRACTIONS = {"½": ".5", "¼": ".25", "¾": ".75"}
_FRACTION = re.compile(r"(\d+)?\s?([½¼¾])")
_DEFANG = [(re.compile(r"\[\.\]|\(\.\)|\{\.\}|\[dot\]", re.I), "."), (re.compile(r"\[:\]"), ":"),
           (re.compile(r"\bhxxp", re.I), "http"), (re.compile(r"\[@\]|\[at\]", re.I), "@")]


def normalize(text: str) -> str:
    """The text as the model read it (NFKC), with Unicode spaces and dashes made plain and soft
    hyphens or zero-width characters removed, so "085 111 2233" with no-break spaces is a phone."""
    # Vulgar fractions first: NFKC would turn "1½" into "11⁄2".
    text = _FRACTION.sub(lambda m: (m.group(1) or "0") + _FRACTIONS[m.group(2)], text or "")
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", _DASHES.sub("-", _SPACES.sub(" ", text)))
    for rx, plain in _DEFANG:  # defanged indicators ("10[.]0[.]0[.]1", "hxxps://") are the same value
        text = rx.sub(plain, text)
    return text


def _not_phone(raw: str) -> bool:
    if raw.startswith(("+", "00")):
        return False
    if _RANGE.fullmatch(raw):
        a, b = re.split(r"\s*[-–]\s*", raw)
        return len(a) == len(b) and len(a) <= 6  # 2023-2024; a real number is "02-1234567"
    m = _AMOUNT.fullmatch(raw)
    # "1.000.000" and "1,250,000" are amounts; groups split by spaces are a phone ("800 123 456"):
    # both texts are read the same way, so the same number still matches.
    return bool(m) and m.group(1) not in (" ", "\u00a0", "\u202f")


@dataclass
class Value:
    kind: str
    key: str
    text: str      # as written
    start: int


def _seconds(number: str, unit: str) -> float | None:
    n = _WORDS[number.lower()] if number.lower() in _WORDS else float(number.replace(",", "."))
    for pattern, factor in _UNITS:
        if re.fullmatch(pattern, unit, re.I):
            return n * factor
    return None


def _time_key(m: re.Match) -> str:
    h, mm, half = int(m.group(1)), m.group(2) or "00", (m.group(3) or "").lower()
    if half and h <= 12:
        h = h % 12 + (12 if half == "p" else 0)
    seconds = re.match(r"[:.]\d\d(:\d\d)", m.group(0)[len(m.group(1)):])
    return f"{h}:{mm}" + (seconds.group(1) if seconds and seconds.group(1) != ":00" else "")


def _date_key(raw: str) -> str:
    parts = re.split(r"[./-]", raw)
    if len(parts[0]) == 4:  # ISO 2024-03-01 -> 1/3/2024
        parts = [parts[2], parts[1], parts[0]]
    return "/".join(str(int(p)) for p in parts)


def _phones(text: str, a: int, b: int) -> list[tuple[int, int]]:
    """A phone match cleaned up: an unclosed "(" ends it ("0851112233 (24/7)"), and two numbers
    joined by " - " or " / " are two numbers."""
    raw = text[a:b]
    k = raw.rfind("(")
    if k > 0 and ")" not in raw[k:]:
        raw = raw[:k].rstrip(" -.")
    out, pos = [], 0
    for piece in re.split(r"(\s[-–/]\s)", raw):
        if piece and not re.fullmatch(r"\s[-–/]\s", piece):
            out.append((a + pos, a + pos + len(piece)))
        pos += len(piece)
    return out


def _num(raw: str) -> str:
    return f"{float(raw.replace(',', '.')):g}"


_JOIN = re.compile(r"\s*(?:,|and|e|ed)?\s*$", re.I)


def _compound(text: str, out: list[Value]) -> list[Value]:
    """"1 hour 30 minutes" / "1 ora e 30 minuti" is one duration (90 minutes), so it matches "90 min"."""
    durs = sorted((v for v in out if v.kind == "duration" and not v.key.startswith("R")), key=lambda v: v.start)
    merged, skip = [], set()
    for a, b in zip(durs, durs[1:]):
        if id(a) in skip:
            continue
        gap = text[a.start + len(a.text):b.start]
        if len(gap) <= 6 and _JOIN.fullmatch(gap) and float(a.key) > float(b.key):
            merged.append(Value("duration", f"{float(a.key) + float(b.key):g}", text[a.start:b.start + len(b.text)], a.start))
            skip.update((id(a), id(b)))
    return [v for v in out if id(v) not in skip] + merged


def extract(text: str, passage: bool = False) -> list[Value]:
    """Values of `text`. For a passage (`passage=True`) a range also gives its two bounds, so an
    answer may state either end ("up to 4 hours" from "2-4 hours")."""
    # Citation markers ("[2]") are not values; blanked, so positions stay those of the text.
    text = re.sub(r"\[\d{1,3}\](?!\()", lambda c: " " * len(c.group()), normalize(text))
    out: list[Value] = []
    bounds: list[Value] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            a, b = m.span()
            if kind == "phone":
                # A number written right before a time or a date ("0851112233 08:00-20:00") keeps
                # the part before them.
                stops = [x for x, y in taken if a < x < b]
                if stops:
                    b = min(stops)
                    while b > a and not text[b - 1].isdigit():
                        b -= 1
                for pa, pb in _phones(text, a, b):
                    raw = text[pa:pb].strip()
                    digits = re.sub(r"\D", "", raw)
                    if not free(pa, pb) or len(digits) < 7 or len(digits) > 15 or _not_phone(raw):
                        continue
                    key = digits[2:] if raw.startswith("00") else digits
                    out.append(Value(kind, key, raw, pa))
                    taken.append((pa, pb))
                continue
            if not free(a, b):
                continue
            raw = m.group(0)
            if kind in ("email", "hash", "domain"):
                key = raw.lower()
            elif kind == "url":
                raw = raw.rstrip(".,;:!?")
                b = a + len(raw)
                key = raw.lower().rstrip("/")
            elif kind == "path":
                raw = raw.rstrip(".,;:!?")
                b = a + len(raw)
                key = raw.lower()
            elif kind == "mac":
                key = raw.lower().replace("-", ":")
            elif kind in ("event", "port", "extension"):
                key = str(int(m.group(1)))
            elif kind == "number":
                key = _num(raw)
            elif kind == "range":
                unit = m.group(3)
                lo, hi = _seconds(m.group(1), unit), _seconds(m.group(2), unit)
                if lo is None or hi is None:
                    continue
                out.append(Value("duration", f"R{lo:g}-{hi:g}", raw.strip(), a))
                if passage:
                    bounds += [Value("duration", f"{lo:g}", raw, a), Value("duration", f"{hi:g}", raw, a)]
                taken.append((a, b))
                continue
            elif kind == "trange":  # "9-11 PM": two times, both with the half of the day
                half = m.group(3).lower()
                for h in (int(m.group(1)), int(m.group(2))):
                    out.append(Value("time", f"{h % 12 + (12 if half == 'p' else 0)}:00", raw.strip(), a))
                taken.append((a, b))
                continue
            elif kind == "hm":
                kind, key = "duration", f"{int(m.group(1)) * 3600 + int(m.group(2)) * 60:g}"
            elif kind == "ip":
                if ":" in raw and "." not in raw and (raw.count(":") < 2 or not re.search(r"[a-fA-F]|::", raw)):
                    continue  # "12:30:45" is a time, not IPv6
                key = raw.lower()
            elif kind == "time":
                key = _time_key(m)
            elif kind == "duration":
                secs = _seconds(m.group(1), m.group(2))
                if secs is None:
                    continue
                key = f"{secs:g}"
            elif kind == "percent":
                key = f"{float(m.group(1).replace(',', '.')):g}"
            elif kind == "date":
                key = _date_key(raw)
            else:
                key = raw.upper()
            out.append(Value(kind, key, raw.strip(), a))
            taken.append((a, b))
    out = _compound(text, out) + bounds
    if passage:  # a number written as a word in the passage ("five attempts") matches "5"
        out += [Value("number", f"{_WORDS[w.lower()]:g}", w, m.start())
                for m in re.finditer(rf"\b({_WORD_RE})\b", text, re.I) for w in [m.group(1)]]
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
    """Whether `a` (from the answer) states the value `b` (from a passage)."""
    if a.kind == "number":
        # A plain number in the answer matches the same number written as a number, an event ID, a
        # port or an extension in the passage ("4625" for "Event ID 4625"); never digits taken from
        # inside a phone, an address or a hash.
        return b.kind in ("number", "event", "port", "extension") and b.key == a.key
    if {a.kind, b.kind} == {"duration", "time"}:
        # "21h" is a clock time too: it matches 21:00.
        d, t = (a, b) if a.kind == "duration" else (b, a)
        m = re.fullmatch(r"(\d{1,2})\s*h", d.text.strip(), re.I)
        return bool(m) and int(m.group(1)) < 24 and t.key == f"{int(m.group(1))}:00"
    if a.kind != b.kind:
        return False
    if a.kind == "phone":
        if a.key == b.key:
            return True
        # The same national number with and without its international prefix: "+39 085…" = "085…".
        # Never a number missing digits ("331234567" is not "+39 333 1234567").
        (short, s), (long_, l) = sorted(((a.key, a), (b.key, b)), key=lambda x: len(x[0]))
        prefix = long_[: len(long_) - len(short)]
        international = l.text.startswith(("+", "00"))
        # Only the passage may carry the prefix: an answer adding one ("+44 085…" for "085…") invents it.
        return l is b and international and long_.endswith(short) and prefix in _COUNTRY and len(short) >= 8
    if a.kind == "ip" and a.key != b.key:
        # "10.0.0.5" written without the port the source gives ("10.0.0.5:8080") is the same host;
        # a different port is a different value.
        host = lambda k: k.rsplit(":", 1)[0] if k.count(".") == 3 and ":" in k else k  # noqa: E731
        return a.key == host(a.key) and host(b.key) == a.key and "." in a.key  # a: the answer's value
    return a.key == b.key


def check(answer: str, cited: dict[int, str], all_passages: list[str]) -> list[dict]:
    """Issues for values of `answer` that are in none of the passages given to the model.

    `cited`: passage number -> text, for the expected value ("the source says ...") only when the
    sources leave one candidate of the same kind.
    """
    known = [v for p in all_passages for v in extract(p, passage=True)]
    answer_values = extract(answer)
    issues = []
    for v in answer_values:
        if any(_same(v, k) for k in known):
            continue
        source_values = [k for t in cited.values() for k in extract(t) if k.kind == v.kind and not k.key.startswith("R")]
        unused = [k for k in source_values if not any(_same(k, a) for a in answer_values)]
        keys = {k.key for k in unused}
        issue = {"level": [1], "kind": "value", "text": v.text, "value_kind": v.kind}
        if len(keys) == 1:
            issue["expected"] = unused[0].text
        elif v.kind in ("phone", "email", "ip", "code", "hash") and unused:
            # A typo-like difference (5656 vs 5566): the closest value, when clearly the closest.
            ranked = sorted({k.key: k for k in unused}.values(), key=lambda k: _distance(v.key, k.key))
            d = [_distance(v.key, k.key) for k in ranked]
            if d[0] <= 2 and (len(d) == 1 or d[1] > d[0]):
                issue["expected"] = ranked[0].text
        issues.append(issue)
    return issues
