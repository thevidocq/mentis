"""Mock HTTP answers shaped like a real server's: the body is a stream not read yet, so SafeHttp
reads it raw (iter_raw) and inflates it itself, as in production."""
import json as _json

import httpx


def answer(status: int, *, json=None, content: bytes = b"", headers: dict | None = None) -> httpx.Response:
    headers = dict(headers or {})
    if json is not None:
        content = _json.dumps(json).encode()
        headers.setdefault("content-type", "application/json")
    return httpx.Response(status, headers=headers, stream=httpx.ByteStream(content))
