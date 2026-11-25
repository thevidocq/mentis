"""Validation of uploaded documents, before anything is stored or parsed.

Only four formats are accepted. A file must match its extension by content (magic bytes and,
for Office files, internal structure). Macro-enabled and encrypted files are refused.
"""

import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass

from app.core.config import get_settings

ALLOWED = {"pdf", "docx", "pptx", "xlsx"}
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
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    if not name:
        raise UploadError("The file has no name.")
    if len(name) > 200:
        stem, _, ext = name.rpartition(".")
        name = f"{stem[:190]}.{ext}" if stem else name[:200]
    return name


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


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
            if any(m in n for n in names for m in _MACRO_MARKERS) or "macroEnabled" in content_types:
                raise UploadError("Files containing macros are not accepted.")
    except zipfile.BadZipFile:
        # Password-protected Office files are not zip archives (they are OLE containers).
        if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise UploadError("Encrypted or old-format Office files are not accepted.") from None
        raise UploadError(f"The file is not a valid .{file_type} document.") from None


def _check_pdf(data: bytes) -> None:
    if not data[:1024].lstrip().startswith(b"%PDF-"):
        raise UploadError("The file is not a valid PDF.")
    if b"/Encrypt" in data[-4096:] or b"/Encrypt" in data[:4096]:
        raise UploadError("Password-protected PDFs are not accepted.")


def check_upload(filename: str, data: bytes) -> CheckedFile:
    name = safe_filename(filename)
    ext = _extension(name)
    if ext in REFUSED_HINT:
        raise UploadError(f".{ext}: {REFUSED_HINT[ext]}.")
    if ext not in ALLOWED:
        raise UploadError("Only PDF, DOCX, PPTX and XLSX files are accepted.")
    size = len(data)
    if size == 0:
        raise UploadError("The file is empty.")
    if size > get_settings().max_upload_mb * 1024 * 1024:
        raise UploadError(f"The file is larger than {get_settings().max_upload_mb} MB.")
    if ext == "pdf":
        _check_pdf(data)
    else:
        _check_ooxml(data, ext)
    return CheckedFile(filename=name, file_type=ext, size=size, sha256=hashlib.sha256(data).hexdigest())
