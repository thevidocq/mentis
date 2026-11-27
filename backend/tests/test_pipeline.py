"""Robustness of the document pipeline: queue outages, index errors, model changes, huge rows, deletes."""

import uuid

from app.core import db as db_module
from app.ingestion.chunking import MAX_CHARS, chunk_pages
from app.ingestion.types import ExtractedPage
from app.models import DocumentVersion, VersionStatus
from app.services import jobs, vector_index
from app.worker import tasks
from tests.conftest import run_jobs
from tests.test_chat import _analyst, _provider, fake_llm  # noqa: F401 - fixture
from tests.test_indexing import _docx, _points, _tenant, _upload


def test_upload_survives_a_queue_outage(super_admin, monkeypatch):
    t = _tenant(super_admin, "Alfa")

    def down(*_a, **_k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(jobs, "enqueue_ingest", down)
    v = _upload(super_admin, t["id"], "A.docx", _docx("Alfa procedure"))
    assert v["status"] == "queued"  # the worker's recovery queues it again later


def test_reindex_without_documents_records_the_new_model(super_admin):
    t = _tenant(super_admin, "Alfa")
    _upload(super_admin, t["id"], "A.docx", _docx("Alfa procedure"))
    run_jobs(super_admin)
    doc = super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]
    super_admin.delete(f"/api/tenants/{t['id']}/documents/{doc['id']}")
    super_admin.put("/api/platform/embedding", json={"model": "other-model"})
    assert super_admin.post("/api/platform/embedding/reindex").status_code == 202
    run_jobs(super_admin)
    assert super_admin.get("/api/platform/embedding").json()["reindex_needed"] is False
    v = _upload(super_admin, t["id"], "B.docx", _docx("Beta procedure"))
    run_jobs(super_admin)
    assert super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{v['id']}").json()["status"] == "ready"


def test_index_errors_become_readable_answers(super_admin, fake_llm, monkeypatch):  # noqa: F811
    _provider(super_admin)
    t = _tenant(super_admin, "Alfa")
    v = _upload(super_admin, t["id"], "A.docx", _docx("Escalate brute force attacks to Mario Rossi"))
    run_jobs(super_admin)

    def broken(*_a, **_k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(vector_index.client(), "query_points", broken)
    an = _analyst(super_admin)
    r = an.post("/api/chats", json={"tenant_id": t["id"], "message": "brute force escalation"})
    assert r.status_code == 201 and r.json()["answer"]["status"] == "error"
    assert "document search service is not available" in r.json()["answer"]["content"]
    r = super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v['id']}/search", json={"question": "brute force"})
    assert r.status_code == 503


def test_model_changed_without_reindex_answers_with_a_clear_error(super_admin, fake_llm):  # noqa: F811
    _provider(super_admin)
    t = _tenant(super_admin, "Alfa")
    _upload(super_admin, t["id"], "A.docx", _docx("Escalate brute force attacks to Mario Rossi"))
    run_jobs(super_admin)
    super_admin.put("/api/platform/embedding", json={"model": "other-model"})
    an = _analyst(super_admin)
    a = an.post("/api/chats", json={"tenant_id": t["id"], "message": "brute force escalation"}).json()["answer"]
    assert a["status"] == "error" and "Reindex" in a["content"]


def test_huge_table_row_is_split_with_its_header():
    row = "| " + ("very long cell text. " * 400) + " | x |"
    page = ExtractedPage(index=1, kind="sheet", label="Contacts", text="| Notes | Id |\n| --- | --- |\n" + row + "\n| short | y |",
                         method="text")
    chunks = chunk_pages([page])
    assert len(chunks) > 2 and all(len(c.text) <= MAX_CHARS for c in chunks)
    assert all(c.text.startswith("| Notes | Id |\n| --- | --- |") for c in chunks)
    assert chunks[-1].text.endswith("| short | y |")


def test_version_deleted_while_processing_leaves_no_points(super_admin, monkeypatch):
    t = _tenant(super_admin, "Alfa")
    v = _upload(super_admin, t["id"], "A.docx", _docx("Alfa procedure about phishing"))
    doc = super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]
    real_on_ready = tasks.versions.on_ready

    def delete_meanwhile(db, version):
        # Another request deletes the document after the points were written, before the commit.
        other = next(db_module.get_db())
        row = other.get(DocumentVersion, version.id)
        assert row is not None and row.status != VersionStatus.READY
        other.close()
        super_admin.delete(f"/api/tenants/{t['id']}/documents/{doc['id']}")
        real_on_ready(db, version)

    monkeypatch.setattr(tasks.versions, "on_ready", delete_meanwhile)
    run_jobs(super_admin)
    assert not [p for p in _points(t["id"]) if p.payload["version_id"] == v["id"]]
    assert next(db_module.get_db()).get(DocumentVersion, uuid.UUID(v["id"])) is None


def test_history_alternates_after_a_failed_answer(super_admin, fake_llm):  # noqa: F811
    _provider(super_admin)
    t = _tenant(super_admin, "Alfa")
    _upload(super_admin, t["id"], "A.docx", _docx("Escalate brute force attacks to Mario Rossi phone 111"))
    run_jobs(super_admin)
    an = _analyst(super_admin)
    chat = an.post("/api/chats", json={"tenant_id": t["id"], "message": "brute force escalation contact"}).json()["chat"]
    fake_llm.fail["api.anthropic.com"] = 500
    assert an.post(f"/api/chats/{chat['id']}/messages", json={"message": "brute force escalation phone"}).json()["answer"]["status"] == "error"
    del fake_llm.fail["api.anthropic.com"]
    an.post(f"/api/chats/{chat['id']}/messages", json={"message": "brute force escalation for critical"})
    roles = [m["role"] for m in fake_llm.requests[-1]["body"]["messages"]]
    assert roles == ["user", "assistant", "user"]


# --- Parsing of real-world layouts ------------------------------------------------

def _parse(data, kind):
    from app.ingestion import ParseLimits, parse

    return parse(data, kind, ParseLimits(max_pages=50))


def test_docx_content_controls_are_read():
    import copy
    import io

    import docx
    from docx.oxml.ns import qn

    d = docx.Document()
    d.add_paragraph("Before the control")
    p = d.add_paragraph("Escalate to Mario Rossi inside a content control")
    sdt = p._p.makeelement(qn("w:sdt"), {})
    content = sdt.makeelement(qn("w:sdtContent"), {})
    content.append(copy.deepcopy(p._p))
    sdt.append(content)
    p._p.addprevious(sdt)
    p._p.getparent().remove(p._p)
    buf = io.BytesIO()
    d.save(buf)
    text = "\n".join(pg.text for pg in _parse(buf.getvalue(), "docx").pages)
    assert "Mario Rossi" in text and "Before the control" in text


def test_pptx_grouped_shapes_are_read():
    import io

    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Escalation flow"
    group = slide.shapes.add_group_shape()
    box = group.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1))
    box.text_frame.text = "Call Laura Bianchi within 15 minutes"
    buf = io.BytesIO()
    prs.save(buf)
    assert "Laura Bianchi" in _parse(buf.getvalue(), "pptx").pages[0].text


# --- Service failures and duplicate jobs -------------------------------------------

def test_approve_and_restore_with_the_index_down_change_nothing(super_admin, monkeypatch):
    t = _tenant(super_admin, "Alfa")
    super_admin.patch(f"/api/tenants/{t['id']}", json={"settings": {"require_approval": True}})
    base = f"/api/tenants/{t['id']}/documents"
    v1 = _upload(super_admin, t["id"], "A.docx", _docx("first"))
    run_jobs(super_admin)
    super_admin.post(f"{base}/versions/{v1['id']}/approve")
    v2 = _upload(super_admin, t["id"], "A.docx", _docx("second"))
    run_jobs(super_admin)

    def down(*_a, **_k):
        raise ConnectionError("qdrant:6333 refused")

    monkeypatch.setattr(vector_index.client(), "set_payload", down)
    r = super_admin.post(f"{base}/versions/{v2['id']}/approve")
    assert r.status_code == 503 and "qdrant" not in r.text
    v2 = super_admin.get(f"{base}/versions/{v2['id']}").json()
    assert v2["approval"] == "pending" and v2["is_active"] is False
    assert super_admin.get(base).json()[0]["active"]["id"] == v1["id"]
    assert super_admin.post(f"{base}/versions/{v1['id']}/restore").status_code == 503


def test_duplicate_ingest_job_keeps_an_approved_version_in_use(super_admin):
    t = _tenant(super_admin, "Alfa")
    super_admin.patch(f"/api/tenants/{t['id']}", json={"settings": {"require_approval": True}})
    v = _upload(super_admin, t["id"], "A.docx", _docx("Alfa procedure about phishing"))
    run_jobs(super_admin)
    super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v['id']}/approve")
    tasks.ingest_version(v["id"])  # recovery queued it again just as the first job finished
    v = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{v['id']}").json()
    assert v["status"] == "ready" and v["approval"] == "approved" and v["is_active"] is True
    assert any(p.payload["active"] for p in _points(t["id"]) if p.payload["version_id"] == v["id"])


def test_service_errors_while_processing_do_not_reach_tenant_admins(super_admin, monkeypatch):
    from qdrant_client.http.exceptions import UnexpectedResponse

    t = _tenant(super_admin, "Alfa")
    v = _upload(super_admin, t["id"], "A.docx", _docx("Alfa procedure"))

    def qdrant_refuses(*_a, **_k):
        raise UnexpectedResponse(500, "Internal Server Error", b"panic at http://qdrant.internal:6333", {})

    monkeypatch.setattr(vector_index.client(), "upsert", qdrant_refuses)
    run_jobs(super_admin)
    v = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{v['id']}").json()
    assert v["status"] == "failed" and v["error"].startswith("Indexing failed") and "qdrant.internal" not in v["error"]

    def minio_down(*_a, **_k):
        raise ConnectionError("HTTPConnectionPool(host='minio.internal', port=9000): Max retries exceeded")

    monkeypatch.setattr(super_admin.storage, "get", minio_down)
    super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v['id']}/retry")
    run_jobs(super_admin)
    v = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{v['id']}").json()
    assert v["status"] == "failed" and "storage" in v["error"] and "minio.internal" not in v["error"]


def test_chunks_keep_their_section_path_and_tables_their_rows():
    from app.ingestion.chunking import chunk_pages as chunks_of
    from app.ingestion.types import ExtractedPage as Page

    text = ("# Ransomware runbook\n\n## Tier 1\n\n### Contacts\n\nCall Mario 0851112233.\n\n## Tier 2\n\n### Contacts\n\n"
            "Call Anna 0852223344.\n\n## Escalation contacts\n\nCall in this order:\n|Name|Phone|\n|:---|---|\n"
            + "\n".join(f"|Analyst {i} with a long role description|+39 333 {i:07d}|" for i in range(60)))
    chunks = chunks_of([Page(index=1, kind="section", label="x", text=text)])
    assert [c.heading for c in chunks[:2]] == ["Ransomware runbook > Tier 1 > Contacts", "Ransomware runbook > Tier 2 > Contacts"]
    assert chunks[2].text.startswith("## Escalation contacts\n\nCall in this order:\n\n|Name|Phone|")  # lead-in with its table
    assert all(c.text.startswith("|Name|Phone|\n|:---|---|") for c in chunks[3:])
    pdf = "\n".join(f"Shift Lead {i} Giovanni Bianchi mobile +39 347 765 {4300 + i}" for i in range(80))
    for c in chunks_of([Page(index=1, kind="page", label="Page 1", text=pdf)]):
        assert all(line.startswith("Shift Lead") and line.split()[-1].isdigit() for line in c.text.split("\n"))


def test_word_reads_text_boxes_insertions_lists_nested_tables_headers():
    import io

    import docx
    from docx.oxml import parse_xml

    w = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
         'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
         'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
         'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"')
    d = docx.Document()
    d.sections[0].header.paragraphs[0].text = "SOC Hotline +39 02 9999 0000"
    p = d.add_paragraph("Before box.")
    p._p.append(parse_xml(f'<w:r {w}><w:drawing><wp:anchor><a:graphic><a:graphicData><wps:wsp><wps:txbx><w:txbxContent>'
                          '<w:p><w:r><w:t>never reboot the DC 10.1.2.3</w:t></w:r></w:p></w:txbxContent></wps:txbx></wps:wsp>'
                          '</a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>'))
    d.element.body.insert(len(d.element.body) - 1, parse_xml(
        f'<w:p {w}><w:r><w:t xml:space="preserve">Call </w:t></w:r><w:ins w:id="1" w:author="x"><w:r><w:t>+39 06 1111</w:t></w:r></w:ins></w:p>'))
    for step in ("Block the sender", "Purge the message", "Reset the password"):
        d.add_paragraph(step, style="List Number")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "Luca Neri"
    t.cell(0, 1).add_table(rows=1, cols=1).cell(0, 0).text = "Backup +39 333 555 6666"
    buf = io.BytesIO()
    d.save(buf)
    text = "\n".join(pg.text for pg in _parse(buf.getvalue(), "docx").pages)
    for expected in ("never reboot the DC 10.1.2.3", "Call +39 06 1111", "1. Block the sender", "3. Reset the password",
                     "Backup +39 333 555 6666", "Page header: SOC Hotline +39 02 9999 0000"):
        assert expected in text, expected


def test_spreadsheet_merged_cells_and_formats():
    import datetime
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Tier", "Name", "Since", "Share"])
    ws.append(["Tier 2", "Luca", datetime.datetime(2024, 3, 1), 0.25])
    ws.append([None, "Sara", None, None])
    ws.merge_cells("A2:A3")
    ws["D2"].number_format = "0%"
    buf = io.BytesIO()
    wb.save(buf)
    text = _parse(buf.getvalue(), "xlsx").pages[0].text
    assert "| Tier 2 | Luca | 2024-03-01 | 25% |" in text and "| Tier 2 | Sara |" in text


def test_html_cells_spanning_rows_stay_in_their_columns():
    from app.ingestion.htmltext import to_markdown

    md, _ = to_markdown(b"<table><tr><th>Tier</th><th>Name</th><th>Phone</th></tr><tr><td rowspan=2>Tier 2</td><td>Luca</td>"
                        b"<td>111</td></tr><tr><td>Sara</td><td>222</td></tr></table>")
    assert "| Tier 2 | Sara | 222 |" in md
