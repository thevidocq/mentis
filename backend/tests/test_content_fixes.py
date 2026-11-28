"""Regressions of the v0.3.1 content review: PDFs with restrictions, Excel formatting, late versions,
reindex queue outage, LLM reply parsing and API keys in error messages."""

import io
import json

import httpx
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions

from app.services import embeddings, jobs, llm
from app.services.uploads import check_upload
from app.worker import tasks
from tests import samples
from tests.conftest import run_jobs
from tests.test_chat import _analyst, _provider, fake_llm  # noqa: F401 - fixture
from tests.test_indexing import _docx, _tenant, _upload


def _protected_pdf(user_password: str) -> bytes:
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(samples.native_pdf())))
    perms = UserAccessPermissions.all() & ~UserAccessPermissions.PRINT & ~UserAccessPermissions.MODIFY
    w.encrypt(user_password=user_password, owner_password="owner", permissions_flag=perms, algorithm="AES-128")
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


# --- Uploads and parsing ----------------------------------------------------------

def test_pdf_with_only_print_copy_restrictions_is_read(super_admin):
    data = _protected_pdf("")
    check_upload("Vendor.pdf", data)  # no password is needed to open it: not refused
    t = _tenant(super_admin, "Alfa")
    v = _upload(super_admin, t["id"], "Vendor.pdf", data)
    run_jobs(super_admin)
    v = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{v['id']}").json()
    assert v["status"] == "ready" and v["is_active"] is True


def test_pdf_needing_a_password_fails_with_a_clear_reason(super_admin):
    t = _tenant(super_admin, "Alfa")
    v = _upload(super_admin, t["id"], "Locked.pdf", _protected_pdf("secret"))
    run_jobs(super_admin)
    v = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{v['id']}").json()
    assert v["status"] == "failed" and v["error"] == "The file is password-protected."


def test_xlsx_formatted_empty_columns_are_dropped():
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from app.ingestion import ParseLimits, parse

    wb = Workbook()
    ws = wb.active
    ws.append(["Contact", "Phone"])
    ws.append(["Mario Rossi", "111"])
    for col in range(1, 2000):  # a whole row formatted, as Excel users often do
        ws.cell(row=3, column=col).font = Font(bold=True)
    buf = io.BytesIO()
    wb.save(buf)
    page = parse(buf.getvalue(), "xlsx", ParseLimits()).pages[0]
    assert page.text == "| Contact | Phone |\n| --- | --- |\n| Mario Rossi | 111 |"


# --- Versions ------------------------------------------------------------------------

def test_version_processed_late_does_not_replace_a_newer_active_one(super_admin, monkeypatch):
    t = _tenant(super_admin, "Alfa")
    _upload(super_admin, t["id"], "Runbook.docx", _docx("first"))
    run_jobs(super_admin)
    monkeypatch.setattr(jobs, "enqueue_ingest", lambda *_a: (_ for _ in ()).throw(ConnectionError("redis down")))
    late = _upload(super_admin, t["id"], "Runbook.docx", _docx("second"))  # stays queued
    monkeypatch.undo()
    newest = _upload(super_admin, t["id"], "Runbook.docx", _docx("third"))
    run_jobs(super_admin)
    tasks.ingest_version(late["id"])  # recovery queues it again, after the newer one went live
    base = f"/api/tenants/{t['id']}/documents"
    assert super_admin.get(base).json()[0]["active"]["id"] == newest["id"]
    late = super_admin.get(f"{base}/versions/{late['id']}").json()
    assert late["status"] == "ready" and late["is_active"] is False
    assert super_admin.post(f"{base}/versions/{late['id']}/restore").json()["is_active"] is True


def test_reindex_with_the_queue_down_can_be_requested_again(super_admin, monkeypatch):
    def down(*_a, **_k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(jobs, "enqueue_reindex", down)
    assert super_admin.post("/api/platform/embedding/reindex").status_code == 503
    assert super_admin.get("/api/platform/embedding").json()["reindex"]["status"] == "failed"
    monkeypatch.undo()
    assert super_admin.post("/api/platform/embedding/reindex").status_code == 202


# --- LLM replies -----------------------------------------------------------------------

def _ask(c, fake, reply: str) -> dict:
    _provider(c)
    t = _tenant(c, "Alfa")
    _upload(c, t["id"], "A.docx", _docx("Escalate brute force attacks to Mario Rossi phone 111"))
    run_jobs(c)
    fake.reply_override = reply
    an = _analyst(c)
    return an.post("/api/chats", json={"tenant_id": t["id"], "message": "brute force escalation contact"}).json()["answer"]


def test_json_answer_with_raw_line_breaks_is_parsed(super_admin, fake_llm):  # noqa: F811
    reply = '{"answer": "Steps:\n1. Call Mario Rossi [1]\n2. Open a ticket", "not_found": false, "followups": "none", "title": null}'
    a = _ask(super_admin, fake_llm, reply)
    assert a["status"] == "ok" and a["content"].startswith("Steps:\n1. Call Mario Rossi [1]")
    assert '"answer"' not in a["content"] and a["followups"] == []  # a string is not a list of questions


def test_json_answer_cut_by_the_token_limit_shows_the_answer_text(super_admin, fake_llm):  # noqa: F811
    a = _ask(super_admin, fake_llm, '{"answer": "Call Mario Rossi [1] at 111.\\nThen open a tic')
    assert a["status"] == "ok" and a["content"].startswith("Call Mario Rossi [1] at 111.\nThen open a tic")
    assert "cut at the length limit" in a["content"]


def _cfg(kind, base="https://llm.example/v1", key="sk-live-0123456789abcdef"):
    return {"name": "P", "kind": kind, "base_url": base, "model": "m", "api_key": key, "options": {}}


@pytest.mark.parametrize("kind,payload", [
    ("anthropic", ["not", "an", "object"]),
    ("anthropic", {"content": ["text block as a string"]}),
    ("openai_responses", {"output": ["x"]}),
    ("openai_chat", {"choices": [{"message": {"content": {"text": "x"}}}]}),
])
def test_unexpected_reply_shapes_are_llm_errors(kind, payload):
    llm.set_transport(httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    try:
        with pytest.raises(llm.LLMError, match="Unexpected answer format"):
            llm.call_provider(_cfg(kind), "s", [llm.Turn("user", "q")])
    finally:
        llm.set_transport(None)


def test_openai_chat_content_as_parts_is_read():
    payload = {"choices": [{"message": {"content": [{"type": "text", "text": "rea"}, {"type": "text", "text": "dy"}]}}]}
    llm.set_transport(httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    try:
        assert llm.call_provider(_cfg("openai_chat"), "s", [llm.Turn("user", "q")]).text == "ready"
    finally:
        llm.set_transport(None)


def test_api_key_echoed_by_a_provider_is_not_in_errors():
    key = "sk-live-0123456789abcdef"

    def echo(req: httpx.Request) -> httpx.Response:
        sent = req.headers.get("authorization") or req.headers.get("x-api-key")
        return httpx.Response(401, text="x" * 160 + json.dumps({"error": f"invalid key {sent}"}))

    llm.set_transport(httpx.MockTransport(echo))
    try:
        for kind in ("anthropic", "openai_chat"):
            with pytest.raises(llm.LLMError) as e:
                llm.call_provider(_cfg(kind, key=key), "s", [llm.Turn("user", "q")])
            assert key[:6] not in str(e.value) and "401" in str(e.value)
            ok, detail = llm.ping(_cfg(kind, key=key))
            assert not ok and key[:6] not in detail
    finally:
        llm.set_transport(None)


def test_embedding_key_echoed_back_is_not_in_errors(monkeypatch):
    embeddings.set_embedder(None)
    key = "emb-secret-0123456789"
    real_client = httpx.Client

    def echo(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"bad token {req.headers['authorization']}")

    monkeypatch.setattr(embeddings.httpx, "Client", lambda timeout: real_client(transport=httpx.MockTransport(echo)))
    with pytest.raises(embeddings.EmbeddingError) as e:
        embeddings.embed({"url": "http://x/v1", "model": "m", "api_key": key}, ["x"])
    assert key not in str(e.value) and "answered 401" in str(e.value)
