"""Maintenance in the worker: the daily retention purge, recovery of stuck document versions and the
checks of documentation read from links.

Every worker replica runs this loop; a Redis lock makes sure only one purge runs per day.
"""

import logging
import threading
import time

from app.core.db import get_db
from app.services import retention
from app.services.jobs import redis_connection
from app.services.logs import log_event
from app.services.recovery import recover_stuck_versions

_log = logging.getLogger("mentis.maintenance")
LOCK = "mentis:maintenance:purge"
ONCE_PER_SECONDS = 23 * 3600


def run_purge_once() -> dict | None:
    if not redis_connection().set(LOCK, "1", nx=True, ex=ONCE_PER_SECONDS):
        return None  # another replica (or an earlier run today) did it
    db = next(get_db())
    try:
        result = retention.purge(db)
        log_event(db, "retention.purged", kind="system", detail=result)
        return result
    except Exception:
        redis_connection().delete(LOCK)  # failed: try again at the next hourly check, not tomorrow
        raise
    finally:
        db.close()


RECOVERY_LOCK = "mentis:maintenance:recovery"


def run_recovery_once() -> dict | None:
    """Stuck versions; one replica every 10 minutes."""
    if not redis_connection().set(RECOVERY_LOCK, "1", nx=True, ex=540):
        return None
    db = next(get_db())
    try:
        result = recover_stuck_versions(db)
        if result["failed"] or result["requeued"]:
            _log.warning("recovered stuck versions: %s", result)
        return result
    finally:
        db.close()


LINKS_LOCK = "mentis:maintenance:links"


def run_link_checks_once() -> dict | None:
    """Links whose check is due (every 10 minutes, one replica); a few per round to stay gentle."""
    from app.services import link_sources

    if not redis_connection().set(LINKS_LOCK, "1", nx=True, ex=540):
        return None
    db = next(get_db())
    try:
        counts = {"new_version": 0, "unchanged": 0, "error": 0}
        for doc in link_sources.due(db):
            try:
                counts[link_sources.sync(db, doc)] += 1
            except Exception:  # noqa: BLE001 - one broken link must not stop the others
                db.rollback()
                counts["error"] += 1
                _log.exception("link check of document %s failed", doc.id)
        if counts["new_version"] or counts["error"]:
            _log.info("link checks: %s", counts)
        return counts
    finally:
        db.close()


def _loop() -> None:
    time.sleep(60)  # let the worker settle after start
    tick = 0
    while True:
        for job, name in ((run_recovery_once, "version recovery"), (run_link_checks_once, "link checks"),
                          (run_purge_once, "retention purge")):
            if job is run_purge_once and tick % 6:
                continue  # the purge is checked every hour, recovery every 10 minutes
            try:
                job()
            except Exception:  # noqa: BLE001 - maintenance must never stop the worker
                _log.exception("%s failed", name)
        tick += 1
        time.sleep(600)


def start() -> None:
    threading.Thread(target=_loop, name="maintenance", daemon=True).start()
