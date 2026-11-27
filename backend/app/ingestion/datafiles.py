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

import yaml

from app.ingestion.text import markdown_table, normalize_text
from app.ingestion.textfiles import decode
from app.ingestion.types import ExtractedPage, ParseLimits, ParseResult

CSV_DELIMITERS = ",;|\t"
CSV_FIELD_LIMIT = 1_000_000          # characters in one cell
YAML_LABEL_KEYS = ("title", "name", "id")
MAX_YAML_NODES = 200_000             # nodes in one file (a file is at most 50 MB of text)


# --- CSV / TSV ------------------------------------------------------------------------------

def _delimiter(text: str, file_type: str) -> str:
    if file_type == "tsv":
        return "\t"
    sample = text[:64_000]
    try:
        return csv.Sniffer().sniff(sample, delimiters=CSV_DELIMITERS).delimiter
    except csv.Error:
        first = sample.split("\n", 1)[0]
        return max(CSV_DELIMITERS, key=first.count) if any(d in first for d in CSV_DELIMITERS) else ","


def read_rows(data: bytes, file_type: str, max_rows: int) -> tuple[list[list[str]], bool]:
    """Rows of a CSV/TSV file and whether it had more than `max_rows`; ValueError if malformed."""
    text = decode(data)
    csv.field_size_limit(CSV_FIELD_LIMIT)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=_delimiter(text, file_type))
    rows: list[list[str]] = []
    try:
        for row in reader:
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

def _count(node, budget: list[int]) -> None:
    """Counts nodes (each alias once, as written) and raises ValueError past the limit."""
    seen, stack = set(), [node]
    while stack:
        n = stack.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        budget[0] -= 1
        if budget[0] < 0:
            raise ValueError("the file has too many values")
        if isinstance(n, yaml.MappingNode):
            stack.extend(x for pair in n.value for x in pair)
        elif isinstance(n, yaml.SequenceNode):
            stack.extend(n.value)


def yaml_documents(text: str) -> list:
    """The documents of a YAML text as nodes (composed, never constructed); ValueError if invalid."""
    budget = [MAX_YAML_NODES]
    try:
        docs = []
        for node in yaml.compose_all(text, Loader=yaml.SafeLoader):
            if node is not None:
                _count(node, budget)
                docs.append(node)
        return docs
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
                return str(found[key]).strip()[:110]
    return f"Document {n}"


def parse_yaml(data: bytes, limits: ParseLimits) -> ParseResult:
    text = decode(data).replace("\r\n", "\n").replace("\r", "\n")
    docs = yaml_documents(text)
    pages = []
    for n, node in enumerate(docs[: limits.max_pages], start=1):
        source = text[node.start_mark.index: node.end_mark.index].strip("\n")
        label = _label(node, n)
        body = f"## {label}\n\n```yaml\n{source}\n```" if source.strip() else ""
        pages.append(ExtractedPage(index=n, kind="section", label=label, text=normalize_text(body)).finalize())
    if not pages:
        pages = [ExtractedPage(index=1, kind="section", label="Document 1", text="").finalize()]
    warnings = [f"Only the first {limits.max_pages} YAML documents were read."] if len(docs) > limits.max_pages else []
    return ParseResult(pages, warnings)
