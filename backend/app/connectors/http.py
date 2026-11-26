"""The HTTP client the core hands to plugins.

It enforces, whatever the plugin does:
- read-only: GET, plus POST only to the URL prefixes the plugin declares as reads (token requests,
  search queries); PUT, PATCH and DELETE never leave Mentis;
- origin binding: requests (and therefore the secrets in them) go only to the instance's origins,
  and redirects are not followed, so a server cannot bounce credentials elsewhere;
- a timeout per request, a cap on the number of requests per call and on the size of each answer.
"""

from typing import Any
from urllib.parse import urlsplit

import httpx

from app.connectors.contract import ConnectorError

MAX_BYTES = 2_000_000
MAX_REQUESTS = 12

_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests route every integration call through a mock transport."""
    global _transport
    _transport = transport


def _origin(url: str) -> tuple[str, str | None, int | None]:
    u = urlsplit(url)
    port = u.port or {"https": 443, "http": 80}.get(u.scheme.lower())
    return u.scheme.lower(), (u.hostname or "").lower() or None, port


class Response:
    def __init__(self, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self.headers = headers
        self._body = body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        import json

        try:
            return json.loads(self._body)
        except ValueError:
            raise ConnectorError("The product returned an answer that is not JSON", retryable=True) from None


class SafeHttp:
    def __init__(self, product: str, origins: list[str], read_posts: list[str], *, timeout: float = 15,
                 max_requests: int = MAX_REQUESTS, max_bytes: int = MAX_BYTES):
        self.product = product
        self._origins = {_origin(o) for o in origins}
        self._posts = [p.rstrip("/") for p in read_posts]
        self._timeout = timeout
        self._left = max_requests
        self._max_bytes = max_bytes
        self.requests = 0

    def _check(self, method: str, url: str) -> None:
        try:
            origin = _origin(url)
        except ValueError:
            raise ConnectorError(f"{self.product}: invalid address", retryable=False) from None
        if origin[0] not in ("http", "https") or origin[1] is None or origin not in self._origins:
            raise ConnectorError(f"{self.product}: request to an address outside this integration refused", retryable=False)
        if method == "GET":
            return
        path = url.split("?", 1)[0].rstrip("/")
        if method == "POST" and any(path == p or path.startswith(p + "/") for p in self._posts):
            return
        raise ConnectorError(f"{self.product}: only read requests are allowed ({method} refused)", retryable=False)

    def request(self, method: str, url: str, *, params: dict | None = None, headers: dict | None = None,
                json: Any = None, data: dict | None = None) -> Response:
        method = method.upper()
        self._check(method, url)
        if self._left <= 0:
            raise ConnectorError(f"{self.product}: too many requests for one question", retryable=False)
        self._left -= 1
        self.requests += 1
        try:
            with httpx.Client(timeout=self._timeout, transport=_transport, follow_redirects=False) as client:
                with client.stream(method, url, params=params, headers=headers, json=json, data=data) as r:
                    chunks, size = [], 0
                    for chunk in r.iter_bytes():
                        size += len(chunk)
                        if size > self._max_bytes:
                            raise ConnectorError(f"{self.product}: answer too large", retryable=False)
                        chunks.append(chunk)
                    return Response(r.status_code, {k.lower(): v for k, v in r.headers.items()}, b"".join(chunks))
        except httpx.TimeoutException:
            raise ConnectorError(f"{self.product} timed out", public=True) from None
        except httpx.HTTPError as e:
            raise ConnectorError(f"{self.product} not reachable: {e.__class__.__name__}", public=True) from None
        except (httpx.InvalidURL, ValueError):
            raise ConnectorError(f"{self.product}: invalid address", retryable=False) from None
