"""The HTTP client the core hands to plugins.

It enforces, whatever the plugin does:
- read-only: GET, plus POST only to the URL prefixes the plugin declares as reads (token requests,
  search queries); PUT, PATCH and DELETE never leave Mentis;
- origin binding: requests (and therefore the secrets in them) go only to the instance's origins,
  and redirects are not followed, so a server cannot bounce credentials elsewhere;
- destination: HTTPS only, never to loopback, link-local (cloud metadata), multicast or reserved
  addresses nor to Mentis' own services (postgres, qdrant, minio, redis, embeddings, web, api);
  private networks and plain HTTP only when the super-admin allows them. The address is resolved
  once and the connection goes to that IP (with the right Host and TLS name), so DNS rebinding
  cannot swap it after the check;
- limits: a total deadline per call (not only per read), a cap on the number of requests per call
  and on the size of each answer after decompression (gzip/deflate inflated here, in bounded steps).
"""

import ipaddress
import socket
import time
import zlib
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.connectors.contract import ConnectorError

MAX_BYTES = 2_000_000
MAX_REQUESTS = 12
DEADLINE = 30.0  # seconds for one plugin call, all its requests together

# Mentis' own services on its Docker networks: never a destination, whatever the settings.
INTERNAL_NAMES = ("postgres", "qdrant", "minio", "redis", "embeddings", "web", "api", "worker", "localhost")
_SHARED = ipaddress.ip_network("100.64.0.0/10")  # carrier-grade NAT, treated as private

_transport: httpx.BaseTransport | None = None
_resolver = None          # tests: host -> list of IP strings
_internal: set | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests route every integration call through a mock transport."""
    global _transport
    _transport = transport


def set_resolver(resolver) -> None:
    """Tests: resolve host names without DNS (resolver(host) -> ["203.0.113.10"])."""
    global _resolver, _internal
    _resolver, _internal = resolver, None


def _origin(url: str) -> tuple[str, str | None, int | None]:
    u = urlsplit(url)
    port = u.port or {"https": 443, "http": 80}.get(u.scheme.lower())
    return u.scheme.lower(), (u.hostname or "").lower() or None, port


def _resolve(host: str, port: int) -> list[str]:
    if _resolver is not None:
        return list(_resolver(host))
    try:
        return sorted({i[4][0] for i in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    except (OSError, UnicodeError, ValueError):  # unresolvable or invalid names (IDNA errors too)
        return []


def _internal_ips() -> set:
    global _internal
    if _internal is None:
        ips = set()
        for name in INTERNAL_NAMES:
            for ip in _resolve(name, 80) if _resolver is None else []:
                try:
                    ips.add(ipaddress.ip_address(ip))
                except ValueError:
                    pass
        _internal = ips
    return _internal


def destination_problem(ip_text: str, allow_private: bool) -> str | None:
    """Why an IP may not be called, or None."""
    try:
        ip = ipaddress.ip_address(ip_text.split("%")[0])
    except ValueError:
        return "invalid address"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return "a local, link-local (cloud metadata) or reserved address"
    if ip in _internal_ips():
        return "a Mentis internal service"
    if not allow_private and (ip.is_private or ip in _SHARED):
        return "a private network address (not allowed here)"
    return None


class Response:
    def __init__(self, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self.headers = headers
        self._body = body

    @property
    def content(self) -> bytes:
        return self._body

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
                 max_requests: int = MAX_REQUESTS, max_bytes: int = MAX_BYTES, deadline: float = DEADLINE,
                 allow_private: bool = False):
        self.product = product
        self._origins = {_origin(o) for o in origins}
        self._posts = [p.rstrip("/") for p in read_posts]
        self._timeout = timeout
        self._left = max_requests
        self._max_bytes = max_bytes
        self._until = time.monotonic() + deadline
        self._allow_private = allow_private
        self.requests = 0

    def _fail(self, message: str) -> ConnectorError:
        return ConnectorError(f"{self.product}: {message}", retryable=False)

    def _check(self, method: str, url: str) -> None:
        try:
            u = urlsplit(url)
            origin = _origin(url)
        except ValueError:
            raise self._fail("invalid address") from None
        if u.username is not None or u.password is not None or u.fragment or "\\" in url:
            raise self._fail("addresses with user names, fragments or backslashes are refused")
        if origin[0] not in ("http", "https") or origin[1] is None or origin not in self._origins:
            raise self._fail("request to an address outside this integration refused")
        if origin[0] == "http" and not self._allow_private:
            raise ConnectorError(f"{self.product}: plain HTTP is refused, use https (or ask a super-admin to allow "
                                 "private addresses)", retryable=False, public=True)
        if method == "GET":
            return
        path = url.split("?", 1)[0].rstrip("/")
        if method == "POST" and ".." not in path and any(path == p or path.startswith(p + "/") for p in self._posts):
            return
        raise self._fail(f"only read requests are allowed ({method} refused)")

    def _pinned(self, url: str) -> tuple[str, dict, dict]:
        """The URL with the checked IP in place of the host name, the Host header and the TLS name."""
        u = urlsplit(url)
        host, port = u.hostname, u.port or (443 if u.scheme == "https" else 80)
        try:
            literal = ipaddress.ip_address(host)
            ips = [str(literal)]
        except ValueError:
            ips = _resolve(host, port)
        if not ips:
            raise ConnectorError(f"{self.product} not reachable: the address does not resolve", public=True)
        for ip in ips:  # every address the name resolves to must be allowed
            problem = destination_problem(ip, self._allow_private)
            if problem:
                raise ConnectorError(f"{self.product}: the address points to {problem}", retryable=False, public=True)
        ip = ips[0]
        netloc = f"[{ip}]" if ":" in ip else ip
        if u.port:
            netloc += f":{u.port}"
        pinned = urlunsplit((u.scheme, netloc, u.path, u.query, ""))
        host_header = host if not u.port else f"{host}:{u.port}"
        ext = {"sni_hostname": host} if u.scheme == "https" else {}
        return pinned, {"Host": host_header}, ext

    def request(self, method: str, url: str, *, params: dict | None = None, headers: dict | None = None,
                json: Any = None, data: dict | None = None) -> Response:
        method = method.upper()
        self._check(method, url)
        if self._left <= 0:
            raise self._fail("too many requests for one question")
        left = self._until - time.monotonic()
        if left <= 0:
            raise ConnectorError(f"{self.product} timed out", public=True)
        self._left -= 1
        self.requests += 1
        pinned, host_header, ext = self._pinned(url)
        hdrs = {**(headers or {}), **host_header, "Accept-Encoding": "gzip, deflate, identity"}
        timeout = httpx.Timeout(min(self._timeout, left))
        try:
            with httpx.Client(timeout=timeout, transport=_transport, follow_redirects=False, trust_env=False) as client:
                with client.stream(method, pinned, params=params, headers=hdrs, json=json, data=data, extensions=ext) as r:
                    body = self._read(r)
                    return Response(r.status_code, {k.lower(): v for k, v in r.headers.items()}, body)
        except httpx.TimeoutException:
            raise ConnectorError(f"{self.product} timed out", public=True) from None
        except httpx.HTTPError as e:
            raise ConnectorError(f"{self.product} not reachable: {e.__class__.__name__}", public=True) from None
        except (httpx.InvalidURL, ValueError):
            raise self._fail("invalid address") from None

    def _read(self, r: httpx.Response) -> bytes:
        """The body, inflated here in bounded steps: the size cap holds after decompression."""
        enc = (r.headers.get("content-encoding") or "identity").lower().strip()
        if enc not in ("identity", "gzip", "x-gzip", "deflate"):
            raise self._fail(f"unsupported answer encoding ({enc[:20]})")
        inflate = None
        chunks, size = [], 0
        for chunk in r.iter_raw():
            if time.monotonic() > self._until:
                raise ConnectorError(f"{self.product} timed out", public=True)
            if enc != "identity" and inflate is None and chunk:
                # gzip and zlib-wrapped deflate have a header; some servers send raw deflate.
                raw = enc == "deflate" and (chunk[0] & 0x0F) != 8
                inflate = zlib.decompressobj(-zlib.MAX_WBITS if raw else 32 + zlib.MAX_WBITS)
            if inflate is not None:
                try:
                    chunk = inflate.decompress(chunk, self._max_bytes - size + 1)
                except zlib.error:
                    raise self._fail("unreadable compressed answer") from None
                if inflate.unconsumed_tail:
                    raise self._fail("answer too large")
            size += len(chunk)
            if size > self._max_bytes:
                raise self._fail("answer too large")
            chunks.append(chunk)
        if inflate is not None:
            try:
                tail = inflate.flush(self._max_bytes - size + 1)
            except zlib.error:
                raise self._fail("unreadable compressed answer") from None
            size += len(tail)
            if size > self._max_bytes:
                raise self._fail("answer too large")
            chunks.append(tail)
        return b"".join(chunks)
