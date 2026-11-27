"""CSV/TSV tables and YAML files.

- CSV / TSV: one table, as for a sheet of a workbook. The CSV delimiter is detected (comma,
  semicolon as in Excel exports with a European locale, pipe or tab). Rows beyond the sheet
  row limit are not read.
- YAML: one section per YAML document (`---`), labelled by its `title`, `name` or `id` (Sigma
  rules, SOAR playbooks, configurations). The text is kept as written, in a `yaml` code block:
  nothing is constructed, so anchors and aliases are never expanded.
"""

import csv
import io
import re

import yaml

from app.ingestion.text import markdown_table, normalize_text
from app.ingestion.textfiles import decode
from app.ingestion.types import ExtractedPage, ParseLimits, ParseResult

CSV_DELIMITERS = ",;|\t"
CSV_FIELD_LIMIT = 1_000_000          # characters in one cell
MAX_COLUMNS = 500                    # wider files are refused (a sheet that wide is not a table to read)
YAML_LABEL_KEYS = ("title", "name", "id")
MAX_YAML_NODES = 200_000             # nodes in one file (a file is at most 50 MB of text)
MAX_YAML_DEPTH = 100                 # nesting levels (libyaml's composer recurses: deeper input crashes it)


# --- CSV / TSV ------------------------------------------------------------------------------

def _consistent(sample: str, delimiter: str) -> bool:
    """Whether most lines of the sample split into the same number (>= 2) of columns."""
    counts = [len(r) for r in csv.reader(io.StringIO(sample, newline=""), delimiter=delimiter) if r][:200]
    if len(counts) < 2:
        return bool(counts) and counts[0] >= 2
    mode = max(set(counts), key=counts.count)
    return mode >= 2 and counts.count(mode) >= 0.8 * len(counts)


def _delimiter(text: str, file_type: str) -> str | None:
    """The column delimiter, or None when the file is a single column (lines of text)."""
    if file_type == "tsv":
        return "\t"
    sample = text[:64_000].rsplit("\n", 1)[0] if len(text) > 64_000 else text
    try:
        found = csv.Sniffer().sniff(sample, delimiters=CSV_DELIMITERS).delimiter
    except csv.Error:
        first = sample.split("\n", 1)[0]
        found = max(CSV_DELIMITERS, key=first.count)
    return found if _consistent(sample, found) else None


def read_rows(data: bytes, file_type: str, max_rows: int) -> tuple[list[list[str]], bool]:
    """Rows of a CSV/TSV file and whether it had more than `max_rows`; ValueError if malformed.

    TSV has no quoting (IANA text/tab-separated-values): a cell starting with `"` is text.
    """
    text = decode(data)
    delimiter = _delimiter(text, file_type)
    if delimiter is None:
        lines = [[line] for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
        return lines[:max_rows], len(lines) > max_rows
    csv.field_size_limit(CSV_FIELD_LIMIT)
    quoting = csv.QUOTE_NONE if file_type == "tsv" else csv.QUOTE_MINIMAL
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quoting=quoting)
    rows: list[list[str]] = []
    try:
        for row in reader:
            if len(row) > MAX_COLUMNS:
                raise ValueError(f"line {reader.line_num} has {len(row)} columns, at most {MAX_COLUMNS} are read")
            if len(rows) >= max_rows:
                return rows, True
            rows.append(row)
    except csv.Error as e:
        raise ValueError(f"line {reader.line_num}: {e}") from None
    return rows, False


def parse_table(data: bytes, file_type: str, limits: ParseLimits) -> ParseResult:
    rows, truncated = read_rows(data, file_type, limits.max_sheet_rows)
    md = markdown_table(rows)
    page = ExtractedPage(index=1, kind="sheet", label="Table", text=normalize_text(md), tables=1 if md else 0)
    warnings = []
    if truncated:
        page.flags.append("truncated")
        warnings.append(f"Only the first {limits.max_sheet_rows} rows were read.")
    return ParseResult([page.finalize()], warnings)


def parse_csv(data: bytes, limits: ParseLimits) -> ParseResult:
    return parse_table(data, "csv", limits)


def parse_tsv(data: bytes, limits: ParseLimits) -> ParseResult:
    return parse_table(data, "tsv", limits)


# --- YAML -----------------------------------------------------------------------------------

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)   # libyaml when available: much faster
_NODE_EVENTS = (yaml.ScalarEvent, yaml.SequenceStartEvent, yaml.MappingStartEvent, yaml.AliasEvent)


def _within_limit(text: str) -> None:
    """Counts values and nesting from the parser events, before any tree is built; ValueError past a limit."""
    left, depth = MAX_YAML_NODES, 0
    for event in yaml.parse(text, Loader=_LOADER):
        if isinstance(event, _NODE_EVENTS):
            left -= 1
            if left < 0:
                raise ValueError(f"the file has more than {MAX_YAML_NODES:,} values")
        if isinstance(event, (yaml.SequenceStartEvent, yaml.MappingStartEvent)):
            depth += 1
            if depth > MAX_YAML_DEPTH:
                raise ValueError("the file is nested too deeply")
        elif isinstance(event, (yaml.SequenceEndEvent, yaml.MappingEndEvent)):
            depth -= 1


def yaml_documents(text: str) -> list:
    """The documents of a YAML text as nodes (composed, never constructed); ValueError if invalid."""
    try:
        _within_limit(text)
        return [node for node in yaml.compose_all(text, Loader=_LOADER) if node is not None]
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1}: " if mark is not None else ""
        raise ValueError(f"{where}{getattr(e, 'problem', None) or 'invalid YAML'}") from None
    except RecursionError:
        raise ValueError("the file is nested too deeply") from None


def _label(node, n: int) -> str:
    if isinstance(node, yaml.MappingNode):
        found = {k.value: v.value for k, v in node.value
                 if isinstance(k, yaml.ScalarNode) and isinstance(v, yaml.ScalarNode) and str(v.value).strip()}
        for key in YAML_LABEL_KEYS:
            if key in found:
                return " ".join(str(found[key]).split())[:110]
    return f"Document {n}"


_MARKER = re.compile(r"^(?:---|\.\.\.)(?=\s|$)[^\n]*\n?", re.MULTILINE)


def _sources(text: str, docs: list) -> list[str]:
    """The text of each document as written, comments included: the text between two documents
    goes to the next one after the last `---`, to the previous one before it."""
    out: list[str] = []
    prev = 0
    for node in docs:
        gap = text[prev: node.start_mark.index]
        markers = list(_MARKER.finditer(gap))
        if markers and out:
            out[-1] += gap[: markers[-1].start()]
        head = gap[markers[-1].end():] if markers else gap
        out.append(head + text[node.start_mark.index: node.end_mark.index])
        prev = node.end_mark.index
    if out:
        out[-1] += _MARKER.sub("", text[prev:])
    return [_MARKER.sub("", x).strip("\n") for x in out]


def parse_yaml(data: bytes, limits: ParseLimits) -> ParseResult:
    text = decode(data).replace("\r\n", "\n").replace("\r", "\n")
    docs = yaml_documents(text)
    pages = []
    for n, (node, source) in enumerate(zip(docs[: limits.max_pages], _sources(text, docs[: limits.max_pages])), start=1):
        label = _label(node, n)
        fence = "`" * max(3, 1 + max((len(m) for m in re.findall(r"`+", source)), default=0))
        body = f"## {label}\n\n{fence}yaml\n{source}\n{fence}" if source.strip() else ""
        pages.append(ExtractedPage(index=n, kind="section", label=label, text=normalize_text(body)).finalize())
    if not pages:
        pages = [ExtractedPage(index=1, kind="section", label="Document 1", text="").finalize()]
    warnings = [f"Only the first {limits.max_pages} YAML documents were read."] if len(docs) > limits.max_pages else []
    return ParseResult(pages, warnings)
