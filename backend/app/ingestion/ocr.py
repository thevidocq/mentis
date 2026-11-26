"""OCR with Tesseract: text plus mean word confidence (0..1)."""

from PIL import Image


MAX_OCR_PIXELS = 40_000_000  # larger pictures are scaled down first (memory and OCR time)


def ocr_image(image: Image.Image, languages: str) -> tuple[str, float | None]:
    import pytesseract

    if image.width * image.height > MAX_OCR_PIXELS:
        ratio = (MAX_OCR_PIXELS / (image.width * image.height)) ** 0.5
        image.draft("L", (int(image.width * ratio), int(image.height * ratio)))  # JPEG: decode smaller
        if image.width * image.height > MAX_OCR_PIXELS:
            ratio = (MAX_OCR_PIXELS / (image.width * image.height)) ** 0.5
            image = image.resize((max(1, int(image.width * ratio)), max(1, int(image.height * ratio))))

    data = pytesseract.image_to_data(image.convert("L"), lang=languages, output_type=pytesseract.Output.DICT)
    lines: dict[tuple, list[str]] = {}
    confidences: list[float] = []
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        conf = float(data["conf"][i])
        if not word or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        confidences.append(conf)
    text = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
    confidence = (sum(confidences) / len(confidences) / 100) if confidences else None
    return text, confidence
