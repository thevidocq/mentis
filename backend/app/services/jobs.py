"""Background jobs on Redis (RQ). Tests replace the runner to execute jobs inline."""

from collections.abc import Callable
from functools import lru_cache

from app.core.config import get_settings

QUEUE = "ingest"

_runner: Callable[[str, str], None] | None = None


def set_runner(runner: Callable[[str, str], None] | None) -> None:
    """runner(job_name, version_id). None restores the Redis queue."""
    global _runner
    _runner = runner


@lru_cache
def redis_connection():
    from redis import Redis

    return Redis.from_url(get_settings().redis_url)


def ingest_job_id(version_id: str) -> str:
    return f"ingest-{version_id}"


def ingest_job_pending(version_id: str) -> bool:
    """True if the version's job is still waiting or running in Redis."""
    from rq.exceptions import NoSuchJobError
    from rq.job import Job, JobStatus

    try:
        job = Job.fetch(ingest_job_id(version_id), connection=redis_connection())
    except NoSuchJobError:
        return False
    return job.get_status() in (JobStatus.QUEUED, JobStatus.STARTED, JobStatus.DEFERRED, JobStatus.SCHEDULED)


def enqueue_ingest(version_id: str) -> None:
    if _runner is not None:
        _runner("ingest", version_id)
        return
    from rq import Queue

    Queue(QUEUE, connection=redis_connection()).enqueue(
        "app.worker.tasks.ingest_version",
        version_id,
        job_id=ingest_job_id(version_id),
        job_timeout=get_settings().ingest_timeout_seconds,
        result_ttl=3600,
        failure_ttl=7 * 24 * 3600,
    )


def enqueue_reindex() -> None:
    if _runner is not None:
        _runner("reindex", "")
        return
    from rq import Queue

    Queue(QUEUE, connection=redis_connection()).enqueue(
        "app.worker.tasks.reindex_all", job_timeout=6 * 3600, result_ttl=3600, failure_ttl=7 * 24 * 3600,
    )


def enqueue_reprocess() -> None:
    if _runner is not None:
        _runner("reprocess", "")
        return
    from rq import Queue

    Queue(QUEUE, connection=redis_connection()).enqueue(
        "app.worker.tasks.reprocess_all", job_timeout=12 * 3600, result_ttl=3600, failure_ttl=7 * 24 * 3600,
    )


def queue_health() -> dict:
    """Redis reachability, workers listening and queue length, for the status page."""
    try:
        from rq import Queue, Worker

        conn = redis_connection()
        conn.ping()
        workers = [w for w in Worker.all(connection=conn) if QUEUE in w.queue_names()]
        return {"redis": True, "workers": len(workers), "queued": len(Queue(QUEUE, connection=conn))}
    except Exception:  # noqa: BLE001 - any failure means the queue is not usable
        return {"redis": False, "workers": 0, "queued": 0}
