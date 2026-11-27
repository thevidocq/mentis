"""Documentation added from a link (first phase: public pages and files).

A document can have a source URL. Mentis reads it when the link is added, then again on a schedule
(every 6 hours, day or week, or only on "Check now"). A change of content becomes a new version
through the same pipeline as an upload (validation, approval, processing); no change only updates the
"last checked" time. When the page cannot be read, the version in use stays and the document shows
the reason.

What is read: web pages (converted to Markdown, content only), Markdown and text files (as Markdown),
PDF, JSON, YAML, CSV. A GitHub file link (github.com/<owner>/<repo>/blob/<ref>/<path>) is read from
its raw version. Pages that need JavaScript to show their text cannot be read.

Requests go through the same guarded client as integrations: HTTPS only, public addresses only
unless the super-admin allows private networks, the address resolved once and pinned, no redirects,
a size cap after decompression and a total deadline. Nothing is sent but a GET with conditional headers.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import unquote, urlsplit, urlunsplit

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.connectors.contract import ConnectorError
from app.connectors.http import SafeHttp
from app.core.config import get_settings
from app.models import Document, DocumentVersion, Tenant, VersionStatus
from app.models.base import utcnow
from app.services import jobs, versions
from app.services.logs import log_event
from app.services.uploads import MIME, UploadError, check_upload, file_type_of, safe_filename

_log = logging.getLogger("mentis.links")

CHECKS = {"6h": timedelta(hours=6), "1d": timedelta(days=1), "7d": timedelta(days=7), "manual": None}
DEFAULT_CHECK = "1d"
DEADLINE = 60.0           # seconds to read one link
MAX_MB = 20               # largest document read from a link (or the upload limit, if lower)
MAX_URL = 2000
USER_AGENT = "Mentis documentation reader"
_GITHUB_BLOB = re.compile(r"^/([^/]+)/([^/]+)/blob/(.+)$")
_BY_EXTENSION = {"md": "md", "markdown": "md", "txt": "md", "text": "md", "pdf": "pdf", "json": "json",
                 "yaml": "yaml", "yml": "yaml", "csv": "csv", "html": "html", "htm": "html"}


class LinkError(ValueError):
    """A link that cannot be added or read; the message is safe to show to tenant admins."""


@dataclass
class Fetched:
    data: bytes
    file_type: str            # one of the upload types (md for pages and text)
    title: str | None
    etag: str | None
    modified: str | None


def check_url(url: str) -> str:
    """The address cleaned up, or LinkError. Only https, no user names, no fragments. Links read public
    addresses only, whatever the integrations setting: a document is shared with the customer's users."""
    url = (url or "").strip()
    if not url or len(url) > MAX_URL:
        raise LinkError("Enter an address of at most 2000 characters.")
    try:
        u = urlsplit(url)
    except ValueError:
        raise LinkError("The address is not valid.") from None
    if u.scheme.lower() != "https" or not u.hostname:
        raise LinkError("The address must start with https://.")
    if u.username is not None or u.password is not None or "\\" in url:
        raise LinkError("Addresses with user names or backslashes are refused.")
    return urlunsplit((u.scheme.lower(), u.netloc, u.path or "/", u.query, ""))


def fetch_url(url: str) -> str:
    """Where to read the document: a GitHub file page is read from its raw version."""
    u = urlsplit(url)
    if u.hostname and u.hostname.lower() in ("github.com", "www.github.com"):
        m = _GITHUB_BLOB.match(u.path)
        if m:
            return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return url


def _extension(url: str) -> str:
    last = unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    return last.rsplit(".", 1)[-1].lower() if "." in last else ""


def _kind(content_type: str, url: str, body: bytes) -> str:
    ct = content_type.split(";", 1)[0].strip().lower()
    ext = _extension(url)
    if ct == "application/pdf" or body[:5] == b"%PDF-":
        return "pdf"
    if ct in ("text/html", "application/xhtml+xml"):
        return "html"
    if ext in _BY_EXTENSION:
        return _BY_EXTENSION[ext]
    if ct in ("text/markdown", "text/plain", "text/x-markdown"):
        return "md"
    if ct in ("application/json",):
        return "json"
    if ct in ("application/yaml", "text/yaml", "application/x-yaml"):
        return "yaml"
    if ct == "text/csv":
        return "csv"
    if body.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")):
        return "html"
    raise LinkError(f"This kind of content cannot be read ({ct or 'unknown type'}). Links to web pages, "
                    "Markdown, text, PDF, JSON, YAML or CSV files are supported.")


def fetch(url: str, *, etag: str | None = None, modified: str | None = None) -> Fetched | None:
    """The document at `url`, or None when the server says it has not changed since etag/modified."""
    target = fetch_url(url)
    client = SafeHttp("The link", [target], [], timeout=30, max_requests=1, deadline=DEADLINE,
                      max_bytes=min(get_settings().max_upload_mb, MAX_MB) * 1024 * 1024, allow_private=False)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html, text/markdown, text/plain, application/pdf, */*;q=0.5"}
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified
    try:
        r = client.request("GET", target, headers=headers)
    except ConnectorError as e:
        raise LinkError(str(e)) from None
    if r.status == 304:
        return None
    if 300 <= r.status < 400:
        where = (r.headers.get("location") or "")[:300]
        raise LinkError(f"The page moved{f' to {where}' if where else ''}: add the new address instead.")
    if r.status in (401, 403):
        raise LinkError(f"The page needs a sign-in (HTTP {r.status}): only public pages can be read for now.")
    if r.status == 404:
        raise LinkError("The page was not found (HTTP 404).")
    if r.status != 200:
        raise LinkError(f"The site answered HTTP {r.status}.")
    body = r.content
    if not body.strip():
        raise LinkError("The page is empty.")
    kind = _kind(r.headers.get("content-type", ""), target, body)
    title = None
    if kind == "html":
        from app.ingestion.htmltext import to_markdown

        try:
            text, title = to_markdown(body, r.headers.get("content-type"))
        except ValueError as e:
            raise LinkError(f"The page could not be read: {e}.") from None
        body, kind = text.encode("utf-8"), "md"
    return Fetched(body, kind, title, (r.headers.get("etag") or "")[:200] or None,
                   (r.headers.get("last-modified") or "")[:100] or None)


def default_name(url: str, fetched: Fetched) -> str:
    """A document name from the address (or the page title), with the extension of what was read."""
    last = unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    stem = last.rsplit(".", 1)[0] if "." in last else last
    if not stem or fetched.title and _extension(url) in ("", "html", "htm"):
        stem = fetched.title or urlsplit(url).hostname or "page"
    stem = " ".join(re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", stem).split())[:150].strip(" .") or "page"
    try:
        return safe_filename(f"{stem}.{fetched.file_type}")
    except UploadError:
        return f"page.{fetched.file_type}"


def _latest(db: Session, doc: Document) -> DocumentVersion | None:
    """The newest version, whatever its state: content that failed is not read again until it changes."""
    return db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
                     .order_by(DocumentVersion.version.desc()).limit(1))


def _new_version(db: Session, tenant: Tenant, doc: Document, fetched: Fetched, user_id, note: str) -> DocumentVersion:
    if file_type_of(doc.name) != fetched.file_type:  # .markdown / .yml names after a rename are the same type
        raise LinkError(f"The link now returns a {fetched.file_type.upper()} file instead of a "
                        f"{doc.name.rsplit('.', 1)[-1].upper()} one: add it as a new document.")
    name = doc.name
    try:
        checked = check_upload(name, fetched.data)
    except UploadError as e:
        raise LinkError(str(e)) from None
    version = versions.store_version(db, tenant.id, doc, filename=checked.filename, file_type=checked.file_type,
                                     data=fetched.data, sha256=checked.sha256, content_type=MIME[checked.file_type],
                                     user_id=user_id, note=note)
    try:
        jobs.enqueue_ingest(str(version.id))
    except Exception:  # noqa: BLE001 - the version is stored; recovery queues it again
        _log.warning("could not queue version %s; recovery will retry", version.id)
    return version


def add(db: Session, tenant: Tenant, url: str, name: str | None, check: str, user_id) -> tuple[Document, DocumentVersion]:
    """Read a link for the first time and create its document (LinkError with a reason otherwise)."""
    if check not in CHECKS:
        raise LinkError("Choose how often to check the page.")
    url = check_url(url)
    fetched = fetch(url)
    assert fetched is not None  # no conditional headers on a first read
    try:
        doc_name = safe_filename(name.strip()) if name and name.strip() else default_name(url, fetched)
    except UploadError as e:
        raise LinkError(str(e)) from None
    if "." not in doc_name or doc_name.rsplit(".", 1)[1].lower() != fetched.file_type:
        doc_name = f"{doc_name.rsplit('.', 1)[0] if '.' in doc_name else doc_name}.{fetched.file_type}"
    if db.scalar(select(Document.id).where(Document.tenant_id == tenant.id, Document.name_key == doc_name.lower())):
        raise LinkError(f"A document named {doc_name} already exists: choose another name.")
    sha = hashlib.sha256(fetched.data).hexdigest()
    versions.lock_content(db, tenant.id, sha)
    duplicate = versions.duplicate_message(db, tenant.id, sha, None)
    if duplicate:  # the same rule as uploads: any document or version of the customer
        raise LinkError(duplicate.replace("This file is", "This content is"))
    doc = Document(tenant_id=tenant.id, name=doc_name, name_key=doc_name.lower(), created_by=user_id, source_url=url,
                   source_check=check, source_checked_at=utcnow(), source_status="new_version",
                   source_etag=fetched.etag, source_modified=fetched.modified)
    db.add(doc)
    db.flush()
    version = _new_version(db, tenant, doc, fetched, user_id, "Added from link")
    return doc, version


def sync(db: Session, doc: Document, user_id=None) -> str:
    """Read the link again: "new_version", "unchanged" or "error" (the reason in doc.source_error)."""
    tenant = db.get(Tenant, doc.tenant_id)
    if tenant is None or not doc.source_url:
        return "error"
    # One check at a time per document (the worker and a "Check now" click): lock the row, then read.
    db.execute(select(Document.id).where(Document.id == doc.id).with_for_update())
    db.refresh(doc)
    latest = _latest(db, doc)
    try:
        fetched = fetch(doc.source_url, etag=doc.source_etag if latest else None, modified=doc.source_modified if latest else None)
        if fetched is None or (latest is not None and hashlib.sha256(fetched.data).hexdigest() == latest.sha256):
            result = "unchanged"
        else:
            version = _new_version(db, tenant, doc, fetched, user_id, "Page changed")
            result = "new_version"
            log_event(db, "document.link_changed", kind="system" if user_id is None else "user", tenant_id=tenant.id,
                      target=doc.name, detail={"version": version.version, "url": doc.source_url})
        if fetched is not None:
            doc.source_etag, doc.source_modified = fetched.etag, fetched.modified
        doc.source_status, doc.source_error = result, None
    except (LinkError, versions.VersionConflict, versions.StorageDown) as e:
        result = "error"
        doc.source_status, doc.source_error = "error", str(e)[:300]
        _log.warning("link of %s (%s) not read: %s", doc.name, doc.source_url, e)
    doc.source_checked_at = utcnow()
    db.commit()
    return result


def due(db: Session, limit: int = 20) -> list[Document]:
    """Linked documents whose next check is due, oldest check first (active customers only)."""
    now = utcnow()
    rows = db.scalars(select(Document).join(Tenant, Tenant.id == Document.tenant_id)
                      .where(Document.source_url.is_not(None), Document.source_check.in_(["6h", "1d", "7d"]),
                             Tenant.status != "disabled",
                             or_(Document.source_checked_at.is_(None),
                                 Document.source_checked_at <= now - CHECKS["6h"]))
                      .order_by(Document.source_checked_at.asc().nulls_first()).limit(500)).all()
    def last(d: Document):
        t = d.source_checked_at
        return t.replace(tzinfo=now.tzinfo) if t is not None and t.tzinfo is None else t  # SQLite drops the zone

    return [d for d in rows if last(d) is None or last(d) + CHECKS[d.source_check] <= now][:limit]
