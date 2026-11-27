"""Builds realistic sample documents in memory, so the repository holds no binary fixtures."""

import io

from PIL import Image, ImageDraw, ImageFont


def _font(size: int):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def text_image(lines: list[str], width=1240, height=600, size=34) -> Image.Image:
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    y = 40
    for line in lines:
        d.text((60, y), line, fill="black", font=_font(size))
        y += int(size * 1.6)
    return img


def native_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    buf = io.BytesIO()
    st = getSampleStyleSheet()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    story = [
        Paragraph("SOC Procedures - Cliente Alfa", st["Title"]),
        Paragraph("Failed logons on domain controllers", st["Heading1"]),
        Paragraph("Check whether the source IP belongs to the customer VPN gateways. "
                  "If the IP is external and not authorised, escalate to the on-call L2 within 30 minutes.", st["BodyText"]),
        Spacer(1, 12),
        Table([["Severity", "Escalation", "Within"], ["High", "On-call L2", "30 minutes"], ["Medium", "Ticket queue", "4 hours"]]),
    ]
    doc.build(story)
    return buf.getvalue()


def scanned_pdf() -> bytes:
    """A PDF whose only page is an image: text must come from OCR."""
    img = text_image(["Escalation matrix", "Primary contact: Mario Rossi", "Phone: 085 123 4567"], height=1754)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150)
    return buf.getvalue()


def docx() -> bytes:
    import docx as d

    doc = d.Document()
    doc.add_heading("Firewall runbook", level=1)
    doc.add_paragraph("Maintenance windows are on Tuesdays from 22:00 to 02:00.")
    doc.add_heading("Contacts", level=2)
    t = doc.add_table(rows=3, cols=2)
    for r, row in enumerate([["Role", "Name"], ["Network lead", "Anna Verdi"], ["Backup", "Luca Neri"]]):
        for c, val in enumerate(row):
            t.cell(r, c).text = val
    doc.add_heading("Rollback", level=1)
    doc.add_paragraph("Restore the previous policy from the backup taken before the change.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def pptx() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = "Brute force playbook"
    s1.placeholders[1].text = "Collect sign-in logs\nIdentify targeted accounts\nBlock source at the edge"
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Escalation flow"
    rows = s2.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(6), Inches(1)).table
    for r, row in enumerate([["Step", "Owner"], ["Confirm attack", "SOC L1"]]):
        for c, val in enumerate(row):
            rows.cell(r, c).text = val
    img = io.BytesIO()
    text_image(["Call the customer on-call", "within 30 minutes"], width=1000, height=260).save(img, format="PNG")
    img.seek(0)
    s2.shapes.add_picture(img, Inches(1), Inches(3.5), width=Inches(6))
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Contacts"
    ws.append(["Escalation matrix"])
    ws.merge_cells("A1:C1")
    ws.append(["Level", "Name", "Phone"])
    ws.append(["L1", "SOC desk", "085 000 0001"])
    ws.append(["L2", "Mario Rossi", "085 123 4567"])
    sla = wb.create_sheet("SLA")
    sla.append(["Severity", "Response"])
    sla.append(["High", "30 minutes"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def macro_docx() -> bytes:
    """A .docx that carries a VBA project (must be refused)."""
    import zipfile

    src = io.BytesIO(docx())
    out = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr("word/vbaProject.bin", b"\x00" * 64)
    return out.getvalue()


def zip_bomb_xlsx(unzipped_mb: int) -> bytes:
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/big.xml", b"0" * (unzipped_mb * 1024 * 1024))
    return out.getvalue()


def png() -> bytes:
    """A screenshot-like picture with text, transparent background (read on white)."""
    img = text_image(["Escalation: call Mario Rossi", "085 123 4567"]).convert("RGBA")
    img.putdata([(0, 0, 0, 0) if px[:3] == (255, 255, 255) else px for px in img.getdata()])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def jpg() -> bytes:
    buf = io.BytesIO()
    text_image(["Escalation: call Mario Rossi", "085 123 4567"]).convert("RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()
