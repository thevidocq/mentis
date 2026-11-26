"""Plugin tests: run with `pytest plugins/` from the repository root (or inside the api image).

They need only the standard library, pytest and the core contract (`backend/app/connectors/contract.py`):
the HTTP client is a fake that records requests and answers from a table, like the products would.
"""

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent
for p in [ROOT.parent / "backend", *sorted(d for d in ROOT.iterdir() if d.is_dir() and (d / "pyproject.toml").exists())]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


class FakeResponse:
    def __init__(self, status: int, body=None, headers: dict | None = None):
        self.status = status
        self.headers = headers or {}
        self._body = body

    def json(self):
        return self._body

    @property
    def text(self) -> str:
        return self._body if isinstance(self._body, str) else json.dumps(self._body)


class FakeHttp:
    """routes: list of (method, url prefix, response or callable(request) -> response). First match wins."""

    def __init__(self, routes):
        self.routes = routes
        self.requests: list[dict] = []

    def request(self, method, url, *, params=None, headers=None, json=None, data=None):
        req = {"method": method.upper(), "url": url, "params": params or {}, "headers": headers or {}, "json": json, "data": data}
        self.requests.append(req)
        for m, prefix, answer in self.routes:
            if m == req["method"] and url.startswith(prefix):
                return answer(req) if callable(answer) else answer
        return FakeResponse(404, {"error": "no route in the fake"})


@pytest.fixture
def fake_http():
    return FakeHttp


@pytest.fixture
def ok():
    return FakeResponse
