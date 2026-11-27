"""Per-client rate limit for the endpoints anyone can call without a session.

Sign-in, 2FA, password reset, invitation and setup requests are counted per client IP in a
sliding one-minute window. Over the limit the API answers 429 before doing any work, so one
client can neither spray passwords over many accounts nor tie up the server with Argon2 hashing.
The counters live in the API process (one API container); a restart clears them.
"""

import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status

WINDOW_SECONDS = 60
MAX_TRACKED = 50_000  # distinct clients kept in memory; older entries are dropped first


class RateLimiter:
    def __init__(self, limit: int, window: float = WINDOW_SECONDS):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> float | None:
        """Count one request. Returns None if allowed, else the seconds to wait."""
        if self.limit <= 0:
            return None
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                if len(self._hits) >= MAX_TRACKED:
                    self._prune(now)
                q = self._hits[key] = deque()
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return max(1.0, q[0] + self.window - now)
            q.append(now)
            return None

    def _prune(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - self.window]:
            del self._hits[k]
        while len(self._hits) >= MAX_TRACKED:  # still full: forget the oldest clients
            del self._hits[next(iter(self._hits))]


def user_rate_limit(request: Request, user_id, name: str) -> None:
    """Per-user limits for expensive actions (LLM calls, calls to customer systems, exports)."""
    limits: dict | None = getattr(request.app.state, "user_limits", None)
    limiter = (limits or {}).get(name)
    if limiter is None:
        return
    wait = limiter.hit(f"{name}:{user_id}")
    if wait is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Wait a moment and try again.",
                            headers={"Retry-After": str(int(wait) + 1)})


def auth_rate_limit(request: Request) -> None:
    """FastAPI dependency for the unauthenticated auth endpoints."""
    limiter: RateLimiter | None = getattr(request.app.state, "auth_limiter", None)
    if limiter is None:
        return
    ip = request.client.host if request.client else "unknown"
    wait = limiter.hit(ip)
    if wait is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Wait a minute and try again.",
                            headers={"Retry-After": str(int(wait) + 1)})
