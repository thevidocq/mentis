"""Documentation added from a link: first read, checks for changes, errors, safety."""

from datetime import timedelta

import httpx
import pytest

from app.connectors import http as connector_http
from tests import samples
from tests.conftest import run_jobs

PAGE = b"""<html><head><title>Apache runbook</title></head><body><nav>Menu</nav>
<main><h1>Apache CVE-2021-41773</h1><p>Call <b>Mario Rossi</b>, 085 123 4567.</p></main></body></html>"""


class Site:
    """A fake public web site: path -> (status, content type, body, headers)."""

    def __init__(self):
        self.pages: dict[str, tuple] = {}
        self.seen: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        status, ctype, body, headers = self.pages.get(request.url.path, (404, "text/plain", b"", {}))
        if request.headers.get("if-none-match") and request.headers["if-none-match"] == headers.get("etag"):
            return httpx.Response(304)
        return httpx.Response(status, headers={"content-type": ctype, **headers}, content=body)


@pytest.fixture
def site():
    s = Site()
    connector_http.set_resolver(lambda host: ["93.184.216.34"])  # a public address
    connector_http.set_transport(httpx.MockTransport(s.handle))
    yield s
    connector_http.set_transport(None)
    connector_http.set_resolver(None)


def _tenant(c, name="Alfa"):
    return c.post("/api/tenants", json={"name": name}).json()


def _add(c, tid, url, **kw):
    return c.post(f"/api/tenants/{tid}/documents/link", json={"url": url, **kw})


def test_page_is_read_converted_and_versioned(super_admin, site):
    t = _tenant(super_admin)
    site.pages["/runbooks/apache"] = (200, "text/html; charset=utf-8", PAGE, {"etag": '"v1"'})
    r = _add(super_admin, t["id"], "https://docs.example.com/runbooks/apache")
    assert r.status_code == 201, r.text
    assert r.json()["file_type"] == "md" and r.json()["note"] == "Added from link"
    run_jobs(super_admin)
    docs = super_admin.get(f"/api/tenants/{t['id']}/documents").json()
    assert [d["name"] for d in docs] == ["Apache runbook.md"]
    link = docs[0]["link"]
    assert link["url"] == "https://docs.example.com/runbooks/apache" and link["check"] == "1d" and link["status"] == "new_version"
    pages = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{r.json()['id']}/pages").json()
    text = "\n".join(p["text"] for p in pages)
    assert "Mario Rossi" in text and "Menu" not in text

    base = f"/api/tenants/{t['id']}/documents/{docs[0]['id']}"
    # Same content (the server says 304): no new version.
    d = super_admin.post(f"{base}/link/check").json()
    assert d["link"]["status"] == "unchanged" and len(d["versions"]) == 1
    assert site.seen[-1].headers["if-none-match"] == '"v1"'
    # Changed page: a new version.
    site.pages["/runbooks/apache"] = (200, "text/html", PAGE.replace(b"085 123 4567", b"085 999 0000"), {"etag": '"v2"'})
    d = super_admin.post(f"{base}/link/check").json()
    assert d["link"]["status"] == "new_version" and [v["version"] for v in d["versions"]] == [2, 1]
    assert d["versions"][0]["note"] == "Page changed"
    # The page disappears: the version in use stays, the reason is shown.
    site.pages.pop("/runbooks/apache")
    d = super_admin.post(f"{base}/link/check").json()
    assert d["link"]["status"] == "error" and "404" in d["link"]["error"] and len(d["versions"]) == 2
    # Schedule.
    assert super_admin.patch(f"{base}/link", json={"check": "7d"}).json()["link"]["check"] == "7d"
    assert super_admin.patch(f"{base}/link", json={"check": "hourly"}).status_code == 422
    # A linked document gets its versions from the link only.
    files = {"file": ("Apache runbook.md", b"# other\n\ntext", "application/octet-stream")}
    assert super_admin.post(f"/api/tenants/{t['id']}/documents", files=files,
                            data={"document_id": docs[0]["id"]}).status_code == 422


def test_github_file_is_read_from_raw(super_admin, site):
    t = _tenant(super_admin)
    site.pages["/acme/runbooks/main/web/apache.md"] = (200, "text/plain; charset=utf-8", b"# Apache\n\nIsolate the host.\n", {})
    r = _add(super_admin, t["id"], "https://github.com/acme/runbooks/blob/main/web/apache.md", check="manual")
    assert r.status_code == 201, r.text
    assert site.seen[-1].url.host == "raw.githubusercontent.com"
    assert r.json()["original_filename"] == "apache.md"


def test_pdf_link(super_admin, site):
    t = _tenant(super_admin)
    site.pages["/files/escalation.pdf"] = (200, "application/pdf", samples.native_pdf(), {})
    r = _add(super_admin, t["id"], "https://docs.example.com/files/escalation.pdf", name="Escalation")
    assert r.status_code == 201 and r.json()["file_type"] == "pdf" and r.json()["original_filename"] == "Escalation.pdf"


@pytest.mark.parametrize("url,reason", [
    ("http://docs.example.com/a", "https"),
    ("https://user:pw@docs.example.com/a", "user names"),
    ("ftp://docs.example.com/a", "https"),
])
def test_bad_addresses_refused(super_admin, site, url, reason):
    t = _tenant(super_admin)
    r = _add(super_admin, t["id"], url)
    assert r.status_code == 422 and reason in r.json()["detail"]


def test_private_and_internal_addresses_refused(super_admin, site):
    t = _tenant(super_admin)
    for ip in ("10.0.0.5", "169.254.169.254", "127.0.0.1"):
        connector_http.set_resolver(lambda host, ip=ip: [ip])
        r = _add(super_admin, t["id"], "https://intranet.example.com/page")
        assert r.status_code == 422 and "address points to" in r.json()["detail"], ip
    assert not site.seen  # nothing was requested
    # Links are public only, even where integrations may reach private networks.
    super_admin.put("/api/platform/integrations/settings", json={"allow_private": True})
    connector_http.set_resolver(lambda host: ["10.0.0.5"])
    r = _add(super_admin, t["id"], "https://intranet.example.com/page")
    assert r.status_code == 422 and "address points to" in r.json()["detail"]
    assert _add(super_admin, t["id"], "http://docs.example.com/page").status_code == 422


def test_unreadable_pages(super_admin, site):
    t = _tenant(super_admin)
    site.pages["/app"] = (200, "text/html", b"<html><body><div id=root></div><script>x()</script></body></html>", {})
    assert "JavaScript" in _add(super_admin, t["id"], "https://docs.example.com/app").json()["detail"]
    site.pages["/login"] = (403, "text/html", b"no", {})
    assert "sign-in" in _add(super_admin, t["id"], "https://docs.example.com/login").json()["detail"]
    site.pages["/moved"] = (301, "text/html", b"", {"location": "https://elsewhere.example.com/x"})
    assert "moved" in _add(super_admin, t["id"], "https://docs.example.com/moved").json()["detail"]
    site.pages["/bin"] = (200, "application/zip", b"PK\x03\x04", {})
    assert "cannot be read" in _add(super_admin, t["id"], "https://docs.example.com/bin").json()["detail"]
    site.pages["/gz"] = (200, "text/html", b"not gzip at all", {"content-encoding": "gzip"})
    r = _add(super_admin, t["id"], "https://docs.example.com/gz")
    assert r.status_code == 422 and "compressed" in r.json()["detail"]


def test_same_content_and_same_name_refused(super_admin, site):
    t = _tenant(super_admin)
    site.pages["/a"] = (200, "text/markdown", b"# Escalation\n\nCall Mario.\n", {})
    site.pages["/b"] = (200, "text/markdown", b"# Escalation\n\nCall Mario.\n", {})
    assert _add(super_admin, t["id"], "https://docs.example.com/a", name="Escalation.md").status_code == 201
    r = _add(super_admin, t["id"], "https://docs.example.com/b", name="Other.md")
    assert r.status_code == 422 and "identical to Escalation.md v1" in r.json()["detail"]
    # An upload with the linked document's name cannot become a manual version of it.
    files = {"file": ("Escalation.md", b"# Manual\n\nedit\n", "application/octet-stream")}
    assert super_admin.post(f"/api/tenants/{t['id']}/documents", files=files).status_code == 422
    site.pages["/c"] = (200, "text/markdown", b"# Something else\n", {})
    r = _add(super_admin, t["id"], "https://docs.example.com/c", name="Escalation.md")
    assert r.status_code == 422 and "already exists" in r.json()["detail"]


def test_due_checks_run_in_maintenance(super_admin, site):
    from app.core import db as db_module
    from app.models import Document
    from app.models.base import utcnow
    from app.services import link_sources

    t = _tenant(super_admin)
    site.pages["/p"] = (200, "text/markdown", b"# P\n\nOne.\n", {})
    doc_id = None
    for check in ("6h", "manual"):
        r = _add(super_admin, t["id"], "https://docs.example.com/p" if check == "6h" else "https://docs.example.com/p?m=1",
                 name=f"{check}.md", check=check)
        if check == "manual":
            assert r.status_code == 422  # same content as the first one
        else:
            doc_id = super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]["id"]
    db = next(db_module.get_db())
    assert link_sources.due(db) == []  # just checked
    doc = db.get(Document, __import__("uuid").UUID(doc_id))
    doc.source_checked_at = utcnow() - timedelta(hours=7)
    db.commit()
    assert [d.name for d in link_sources.due(db)] == ["6h.md"]
    site.pages["/p"] = (200, "text/markdown", b"# P\n\nTwo.\n", {})
    assert link_sources.sync(db, link_sources.due(db)[0]) == "new_version"
    assert link_sources.due(db) == []


def test_failed_content_is_not_read_again_until_it_changes(super_admin, site):
    from app.core import db as db_module
    from app.models import Document, DocumentVersion, VersionStatus
    from app.services import link_sources

    t = _tenant(super_admin)
    site.pages["/f"] = (200, "text/markdown", b"# F\n\nOne.\n", {})
    assert _add(super_admin, t["id"], "https://docs.example.com/f", name="F.md").status_code == 201
    db = next(db_module.get_db())
    doc = db.query(Document).filter(Document.name == "F.md").one()
    version = db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).one()
    version.status = VersionStatus.FAILED
    db.commit()
    assert link_sources.sync(db, doc) == "unchanged"
    assert db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).count() == 1


def test_page_conversion():
    from app.ingestion.htmltext import to_markdown

    md, _ = to_markdown(b"<div>Call <a href=x>Mario</a> and <b>Anna</b><p>Then escalate.</p></div>")
    assert md == "Call Mario and **Anna**\n\nThen escalate."
    md, _ = to_markdown(b"<ol start=3><li><p>first</p><p>second</p></li><li>x<ul><li>sub</li></ul></li></ol>")
    assert md == "3. first second\n\n4. x\n\n    - sub"
    md, _ = to_markdown(b"<body><form><h1>SharePoint page</h1><p>Body</p><input value=1></form></body>")
    assert md == "# SharePoint page\n\nBody"
    md, _ = to_markdown(b"<table><tr><td>a<table><tr><td>x</td></tr></table></td><td>b</td></tr></table>")
    assert md.splitlines()[0] == "| a x | b |"
    md, _ = to_markdown(b"<body><header>Site</header><main><article><header><h1>Title</h1></header><p>One</p>"
                        b"</article><article><p>Two</p></article></main><footer>(c)</footer></body>")
    assert md == "# Title\n\nOne\n\nTwo"
    assert to_markdown("<p>caf\u00e9</p>".encode(), "text/html")[0] == "caf\u00e9"
    assert to_markdown("<p>caf\u00e9</p>".encode("latin-1"), "text/html; charset=iso-8859-1")[0] == "caf\u00e9"
    md, _ = to_markdown(b"<ol><li><p>Install:</p><pre><code>pip install x\npip install y</code></pre></li></ol>")
    assert md == "1. Install:\n\n    ```\n    pip install x\n    pip install y\n    ```"
    assert to_markdown(b"<ul><li>a<ul><li>b</li></ul>tail</li></ul>")[0] == "- a\n\n    - b\n\n    tail"
    md, _ = to_markdown('<h2>Setup<a class="headerlink" href="#s">\u00b6</a></h2><p>x</p>'.encode(), "text/html")
    assert md == "## Setup\n\nx"
    assert to_markdown(b"<blockquote><p>one</p><p>two</p></blockquote>")[0] == "> one\n\n> two"


def test_page_conversion_is_bounded():
    from app.ingestion.htmltext import to_markdown

    deep = b"<ul>" + b"<li>a<ul>" * 150 + b"<li>x</li>" * 20000 + b"</ul></li>" * 150 + b"</ul>"
    md, _ = to_markdown(deep)
    assert max(len(line) - len(line.lstrip()) for line in md.splitlines()) <= 24  # nesting capped
    md, _ = to_markdown(b"<ul>" + b"<li>item</li>" * 100_000 + b"</ul>", max_chars=50_000)
    assert len(md) < 51_000 and "size limit" in md
