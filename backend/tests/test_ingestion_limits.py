"""Regression tests for the ingestion review of 0.6.2 (docs/security/review-v0.6.2.md, I-1..I-3)."""

import os
import signal
import subprocess
import time

import pytest

from app.ingestion import isolated
from app.ingestion.chunking import chunk_pages
from app.ingestion.textfiles import _heading
from app.ingestion.types import ExtractedPage, ParseLimits, ParseResult


def _page(text: str) -> ExtractedPage:
    return ExtractedPage(index=1, kind="section", label="x", text=text)


@pytest.mark.parametrize("text", [
    "```\n" + "x: 1\n" * 20000 + "```",              # one long code block (Markdown, every YAML document)
    ("|" + " " * 20000 + "\n") * 4,                  # long runs of spaces before a table separator check
    "| a | b |\n|---|---|\n" + "| 1 | 2 |\n" * 20000,  # a long table
])
def test_chunking_is_linear(text):
    t0 = time.monotonic()
    chunks = chunk_pages([_page(text)])
    assert chunks and time.monotonic() - t0 < 3


def test_heading_title_is_linear_and_keeps_closing_hash_rules():
    assert _heading("# C#", "#") == "C#" and _heading("# Title ##", "#") == "Title" and _heading("#x", "#") is None
    t0 = time.monotonic()
    assert _heading("# " + " " * 50000 + "x", "#") == "x"
    assert time.monotonic() - t0 < 1


def test_chunks_are_made_in_the_child():
    result = isolated.parse_isolated(b"# Title\n\nCall Mario.\n", "md", ParseLimits(max_pages=10))
    assert result.chunks and result.chunks[0].text.endswith("Call Mario.")


def test_programs_started_by_the_parser_die_with_it_and_a_timeout_is_not_an_unreadable_file(monkeypatch):
    class JobTimeout(Exception):
        pass

    marker = f"mentis-orphan-{os.getpid()}"

    def slow_parse(data, file_type, limits, parser="standard"):
        subprocess.Popen(["sh", "-c", f"exec -a {marker} sleep 60"])
        time.sleep(60)
        return ParseResult([])

    monkeypatch.setattr("app.ingestion.parse", slow_parse)

    def alarm(*_):
        raise JobTimeout()

    old = signal.signal(signal.SIGALRM, alarm)
    signal.alarm(2)
    try:
        with pytest.raises(JobTimeout):
            isolated.parse_isolated(b"x", "txt", ParseLimits(max_pages=1))
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
    time.sleep(0.5)
    alive = subprocess.run(["ps", "-eo", "stat,args"], capture_output=True, text=True).stdout.splitlines()
    assert not [p for p in alive if marker in p and not p.startswith("Z")]


def test_self_approval_follows_the_setting(super_admin):
    from tests import samples
    from tests.conftest import run_jobs

    t = super_admin.post("/api/tenants", json={"name": "Four Eyes"}).json()
    super_admin.patch(f"/api/tenants/{t['id']}", json={"settings": {"require_approval": True}})
    r = super_admin.post(f"/api/tenants/{t['id']}/documents",
                         files={"file": ("Runbook.docx", samples.docx(),
                                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 201, r.text
    run_jobs(super_admin)
    vid = r.json()["id"]
    super_admin.patch(f"/api/tenants/{t['id']}", json={"settings": {"approval_by_another": True}})
    r = super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{vid}/approve")
    assert r.status_code == 409 and "someone other" in r.json()["detail"]
    super_admin.patch(f"/api/tenants/{t['id']}", json={"settings": {"approval_by_another": False}})
    assert super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{vid}/approve").status_code == 200
    logs = super_admin.get("/api/logs", params={"q": "version_approved"}).json()
    items = logs.get("items", logs) if isinstance(logs, dict) else logs
    assert any((i.get("detail") or {}).get("self_approved") for i in items)
