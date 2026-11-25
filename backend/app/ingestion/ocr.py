"""OCR with Tesseract: text plus mean word confidence (0..1)."""

from PIL import Image


def ocr_image(image: Image.Image, languages: str) -> tuple[str, float | None]:
    import pytesseract

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
