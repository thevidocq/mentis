"""Daily storage sweep: removes files and vectors that no database row refers to any more.

Deleting a document, a version or a tenant removes its rows first and then its files (MinIO) and
vectors (Qdrant). If one of those services is down at that moment, the leftovers stay: they are
invisible and unused, but take space. This sweep finds and removes them.

Safe by construction: a version's row is written before its files and vectors, so anything under
an id that has no row is a leftover.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentVersion, Tenant
from app.services import storage, vector_index

_log = logging.getLogger("mentis.sweep")


def sweep(db: Session) -> dict:
    tenants = {t.id.hex: t.id for t in db.scalars(select(Tenant))}
    known = {str(v) for v in db.scalars(select(DocumentVersion.id))}
    result = {"files": 0, "vectors": 0}
    store = storage.get_storage()

    # Files: tenants/<tenant>/versions/<version>/...
    for tdir in store.list_dirs("tenants/"):
        try:
            tid = uuid.UUID(tdir)
        except ValueError:
            continue
        if tid.hex not in tenants:
            store.delete_prefix(f"tenants/{tdir}/")
            result["files"] += 1
            continue
        for vdir in store.list_dirs(f"tenants/{tdir}/versions/"):
            if vdir not in known:
                store.delete_prefix(f"tenants/{tdir}/versions/{vdir}/")
                result["files"] += 1

    # Vectors: one collection per tenant, points carry their version id.
    try:
        collections = vector_index.tenant_collections()
    except Exception:  # noqa: BLE001 - Qdrant down: try again tomorrow
        _log.warning("storage sweep: Qdrant not reachable, vectors skipped", exc_info=True)
        return result
    for name, thex in collections.items():
        if thex not in tenants:
            vector_index.delete_collection(name)
            result["vectors"] += 1
            continue
        try:
            if vector_index.move_vectors_to_disk(name):
                _log.info("vectors of %s moved to disk", name)
        except Exception:  # noqa: BLE001 - an optimisation, not a cleanup: never blocks the sweep
            _log.warning("could not move the vectors of %s to disk", name, exc_info=True)
        for vid in vector_index.version_ids(tenants[thex]) - known:
            vector_index.delete_version(tenants[thex], vid)
            result["vectors"] += 1
    return result
