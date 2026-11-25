"""Daily maintenance in the worker: the retention purge.

Every worker replica runs this loop; a Redis lock makes sure only one purge runs per day.
"""

import logging
import threading
import time

from app.core.db import get_db
from app.services import retention
from app.services.jobs import redis_connection
from app.services.logs import log_event

_log = logging.getLogger("mentis.maintenance")
LOCK = "mentis:maintenance:purge"
EVERY_SECONDS = 3600
ONCE_PER_SECONDS = 23 * 3600


def run_purge_once() -> dict | None:
    if not redis_connection().set(LOCK, "1", nx=True, ex=ONCE_PER_SECONDS):
        return None  # another replica (or an earlier run today) did it
    db = next(get_db())
    try:
        result = retention.purge(db)
        log_event(db, "retention.purged", kind="system", detail=result)
        return result
    finally:
        db.close()


def _loop() -> None:
    time.sleep(60)  # let the worker settle after start
    while True:
        try:
            run_purge_once()
        except Exception:  # noqa: BLE001 - maintenance must never stop the worker
            _log.exception("retention purge failed")
        time.sleep(EVERY_SECONDS)


def start() -> None:
    threading.Thread(target=_loop, name="maintenance", daemon=True).start()
