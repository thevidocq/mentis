"""Pictures (PNG, JPEG): screenshots of escalation matrices, photos of procedures, diagrams.

The picture is read with Tesseract OCR (with a confidence score, low values flagged for review)
and kept as the preview image. Phone photos are turned upright first (EXIF orientation).
"""

import io
import struct

from PIL import Image, ImageOps, UnidentifiedImageError

from app.ingestion.ocr import ocr_image
from app.ingestion.text import normalize_text
from app.ingestion.types import ExtractedPage, ParseLimits, ParseResult

MAX_IMAGE_PIXELS = 50_000_000        # refused above this (e.g. 7000 x 7000), at upload and here
PREVIEW_MAX_SIDE = 2000              # preview image, longest side in pixels
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def image_size(data: bytes, file_type: str) -> tuple[int, int]:
    """Width and height from the file header, without decoding; ValueError if not that format."""
    if file_type == "png":
        if data[:8] != PNG_MAGIC or data[12:16] != b"IHDR" or len(data) < 24:
            raise ValueError("not a PNG image")
        return struct.unpack(">II", data[16:24])
    if data[:3] != JPEG_MAGIC:
        raise ValueError("not a JPEG image")
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            raise ValueError("not a JPEG image")
        marker = data[i + 1]
        if marker == 0xFF:          # fill byte
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # markers without a length
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2: i + 4])[0]
        if marker in _JPEG_SOF:
            if i + 9 > len(data):
                break
            height, width = struct.unpack(">HH", data[i + 5: i + 9])
            return width, height
        if marker == 0xDA or length < 2:  # image data starts before any frame header: invalid
            break
        i += 2 + length
    raise ValueError("not a JPEG image")


def _preview(image: Image.Image) -> bytes:
    image = image.convert("RGB")
    image.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE))
    buf = io.BytesIO()
    image.save(buf, format="WEBP", quality=80, method=4)
    return buf.getvalue()


def parse_image(data: bytes, limits: ParseLimits) -> ParseResult:
    try:
        image = Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, Image.DecompressionBombError):
        raise ValueError("The picture could not be read.") from None
    if image.format not in ("PNG", "JPEG", "MPO"):  # MPO: phone JPEGs with a multi-picture header
        raise ValueError("not a PNG or JPEG image")
    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise ValueError(f"the image is larger than {MAX_IMAGE_PIXELS // 1_000_000} million pixels")
    try:
        image.load()
    except (OSError, SyntaxError):  # truncated or corrupt data
        raise ValueError("The picture is damaged and could not be read.") from None
    image = ImageOps.exif_transpose(image) or image
    if image.mode in ("RGBA", "LA", "P"):  # transparent screenshots: text on white, not on black
        rgba = image.convert("RGBA")
        image = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("RGB")
    text, conf = ocr_image(image, limits.ocr_languages)
    page = ExtractedPage(index=1, kind="page", label="Image", text=normalize_text(text), method="ocr",
                         ocr_confidence=conf, image=_preview(image))
    return ParseResult([page.finalize()])
