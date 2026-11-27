"""Validation of uploaded documents, before anything is stored or parsed.

Accepted: PDF, DOCX, PPTX, XLSX, Markdown (.md), JSON, CSV, TSV, YAML and pictures (PNG, JPEG). A file
must match its extension by content (magic bytes; internal structure for Office files; UTF-8 text
for the text formats, which must also parse; a picture header within the pixel limit). Macro-enabled
and encrypted files are refused.
"""

import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass

from app.core.config import get_settings

ALLOWED = {"pdf", "docx", "pptx", "xlsx", "md", "json", "csv", "tsv", "yaml", "png", "jpg"}
TEXT_TYPES = {"md", "json", "csv", "tsv", "yaml"}
IMAGE_TYPES = {"png", "jpg"}
ALIASES = {"markdown": "md", "yml": "yaml", "jpeg": "jpg"}  # stored and shown with the first name
REFUSED_HINT = {
    "docm": "macro-enabled Word files are not accepted; save as .docx",
    "xlsm": "macro-enabled Excel files are not accepted; save as .xlsx",
    "pptm": "macro-enabled PowerPoint files are not accepted; save as .pptx",
    "doc": "old Word format; save as .docx",
    "xls": "old Excel format; save as .xlsx",
    "ppt": "old PowerPoint format; save as .pptx",
}

# The main part each Office format must contain, and the content type that marks a macro-enabled file.
_OOXML_MAIN = {"docx": "word/document.xml", "pptx": "ppt/presentation.xml", "xlsx": "xl/workbook.xml"}
_MACRO_MARKERS = ("vbaProject.bin", "macroEnabled")


class UploadError(ValueError):
    pass


@dataclass
class CheckedFile:
    filename: str
    file_type: str
    size: int
    sha256: str


def safe_filename(name: str) -> str:
    """Display-safe file name: no path, no control characters, bounded length."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFC", name)
    # Control and format characters (e.g. U+202E right-to-left override, which makes
    # "x\u202egnp.pdf" display as "xfdp.png") are dropped.
    name = "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cf"))
    name = name.strip().strip(".")
    if not name:
        raise UploadError("The file has no name.")
    if len(name) > 200:
        stem, _, ext = name.rpartition(".")
        name = f"{stem[:190]}.{ext}" if stem else name[:200]
    return name


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def file_type_of(name: str) -> str:
    """The file type a name stands for, aliases folded: "rule.yml" and "rule.yaml" are both yaml."""
    ext = _extension(name)
    return ALIASES.get(ext, ext)


def _check_ooxml(data: bytes, file_type: str) -> None:
    limit = get_settings().max_unzipped_mb * 1024 * 1024
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            names = {i.filename for i in infos}
            if sum(i.file_size for i in infos) > limit:
                raise UploadError("The file expands to more than the allowed size.")
            if any(i.flag_bits & 0x1 for i in infos):
                raise UploadError("Encrypted files are not accepted.")
            if _OOXML_MAIN[file_type] not in names:
                raise UploadError(f"The file is not a valid .{file_type} document.")
            content_types = zf.read("[Content_Types].xml").decode("utf-8", "replace") if "[Content_Types].xml" in names else ""
            # Part names and content types are case-insensitive in Office files.
            lowered = [n.lower() for n in names]
            if any(m.lower() in n for n in lowered for m in _MACRO_MARKERS) or "macroenabled" in content_types.lower():
                raise UploadError("Files containing macros are not accepted.")
    except zipfile.BadZipFile:
        # Password-protected Office files are not zip archives (they are OLE containers).
        if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise UploadError("Encrypted or old-format Office files are not accepted.") from None
        raise UploadError(f"The file is not a valid .{file_type} document.") from None


def _check_pdf(data: bytes) -> None:
    # An /Encrypt dictionary does not mean a password is needed to open the file: many PDFs only
    # restrict printing or copying and read normally. The worker tells them apart and fails the
    # version with "The file is password-protected." when a password is really required.
    if not data[:1024].lstrip().startswith(b"%PDF-"):
        raise UploadError("The file is not a valid PDF.")


def _check_text(data: bytes, file_type: str) -> None:
    from app.ingestion.textfiles import decode

    try:
        text = decode(data)
    except (ValueError, UnicodeDecodeError):
        raise UploadError(f"The .{file_type} file is not UTF-8 text: save it as UTF-8.") from None
    empty = UploadError("The file has no content to read.")
    if not text.strip():
        raise empty
    if file_type == "json":
        import json

        try:
            if json.loads(text) in ({}, [], None, ""):
                raise empty
        except RecursionError:
            raise UploadError("The JSON file is nested too deeply.") from None
        except ValueError as e:
            raise UploadError(f"The file is not valid JSON ({str(e)[:80]}).") from None
    elif file_type in ("csv", "tsv"):
        from app.ingestion.datafiles import read_rows
        from app.ingestion.types import ParseLimits

        try:
            rows, _ = read_rows(data, file_type, ParseLimits().max_sheet_rows)
        except ValueError as e:
            raise UploadError(f"The file is not a valid .{file_type} table ({str(e)[:80]}).") from None
        if not any(c.strip() for r in rows for c in r):
            raise empty
    elif file_type == "yaml":
        from app.ingestion.datafiles import yaml_documents

        try:
            docs = yaml_documents(text)
        except ValueError as e:
            raise UploadError(f"The file is not valid YAML ({str(e)[:80]}).") from None
        if not docs:
            raise empty


def _check_image(data: bytes, file_type: str) -> None:
    from app.ingestion.images import MAX_IMAGE_PIXELS, image_size

    try:
        width, height = image_size(data, file_type)
    except ValueError:
        raise UploadError(f"The file is not a valid {'PNG' if file_type == 'png' else 'JPEG'} image.") from None
    if width * height > MAX_IMAGE_PIXELS or not width or not height:
        raise UploadError(f"The image is {width} x {height} pixels: at most {MAX_IMAGE_PIXELS // 1_000_000} million are accepted.")


def check_upload(filename: str, data: bytes) -> CheckedFile:
    name = safe_filename(filename)
    ext = file_type_of(name)
    if ext in REFUSED_HINT:
        raise UploadError(f".{ext}: {REFUSED_HINT[ext]}.")
    if ext not in ALLOWED:
        raise UploadError("Only PDF, DOCX, PPTX, XLSX, Markdown (.md), JSON, CSV, TSV, YAML, PNG and JPEG files are accepted.")
    size = len(data)
    if size == 0:
        raise UploadError("The file is empty.")
    if size > get_settings().max_upload_mb * 1024 * 1024:
        raise UploadError(f"The file is larger than {get_settings().max_upload_mb} MB.")
    if ext == "pdf":
        _check_pdf(data)
    elif ext in TEXT_TYPES:
        _check_text(data, ext)
    elif ext in IMAGE_TYPES:
        _check_image(data, ext)
    else:
        _check_ooxml(data, ext)
    return CheckedFile(filename=name, file_type=ext, size=size, sha256=hashlib.sha256(data).hexdigest())
