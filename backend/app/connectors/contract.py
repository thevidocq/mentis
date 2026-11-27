"""The connector contract: what a plugin in `plugins/<name>/` implements.

A plugin is a `Connector` registered under the `mentis.connectors` Python entry point. It never
touches the database or the network on its own: the core passes in the configuration, the
decrypted secrets and an HTTP client that only allows read requests to the plugin's own origins
(see `app.connectors.http`). Every operation is read-only and returns normalized `Record`s.

Standard library only: plugins and their tests must not need the rest of the core.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

CORE_API = "1"

TICKETING, EDR, SIEM, IDENTITY = "ticketing", "edr", "siem", "identity"
TYPES = (TICKETING, EDR, SIEM, IDENTITY)

TICKET, DEVICE, ALERT, INDICATOR, USER = "ticket", "device", "alert", "indicator", "user"
# indicator: an IP, domain or file hash and what the product knows of it; user: an account (identity)
KINDS = (TICKET, DEVICE, ALERT, INDICATOR, USER)


@dataclass(frozen=True)
class Manifest:
    name: str            # entry point name, e.g. "servicenow"
    label: str           # shown in the UI, e.g. "ServiceNow"
    version: str
    type: str            # ticketing | edr | siem | identity
    vendor: str
    description: str
    vertical: str = "soc"
    core_api: str = CORE_API


@dataclass(frozen=True)
class Param:
    description: str
    required: bool = True
    # The value must match this pattern (checked by the core before the plugin runs).
    pattern: str | None = None
    max_length: int = 200
    # An object identifier (ticket number, host name, alert id): logged in the audit entry.
    # Free text (search words) is never logged.
    identifier: bool = True


@dataclass(frozen=True)
class Operation:
    name: str
    label: str
    description: str     # for the planner model: when to use this operation
    returns: str         # ticket | device | alert | indicator | user
    params: dict[str, Param] = field(default_factory=dict)
    # Run without asking a model when the question contains a match: {param: regex}. The whole
    # match becomes the parameter value. Only for identifiers with an unmistakable shape.
    match: dict[str, str] = field(default_factory=dict)


@dataclass
class Record:
    """One normalized object read from a customer system."""

    kind: str                      # ticket | device | alert | indicator | user
    id: str                        # as the analyst knows it: INC0012345, ABC-123, host name, alert id
    title: str
    url: str | None = None         # link to the object in the product's console
    fields: dict[str, str] = field(default_factory=dict)  # ordered label -> value
    text: str | None = None        # long text: description, recent comments
    updated: str | None = None     # ISO time of the last change, when known
    # More pages to open, label -> URL (e.g. "IP 10.0.0.5" -> the product's IP page).
    links: dict[str, str] = field(default_factory=dict)


class ConnectorError(Exception):
    """A plugin failed. `public` messages are safe to show to analysts (no address, no reply body)."""

    def __init__(self, message: str, *, retryable: bool = True, public: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.public = public


class HttpResponse(Protocol):
    status: int
    headers: dict[str, str]

    def json(self) -> Any: ...

    @property
    def text(self) -> str: ...


class Http(Protocol):
    def request(self, method: str, url: str, *, params: dict | None = None, headers: dict | None = None,
                json: Any = None, data: dict | None = None) -> HttpResponse: ...


@dataclass
class Context:
    """What a plugin gets for one call. `state` survives between calls of the same instance
    (e.g. an OAuth token and its expiry); the core drops it when the configuration changes."""

    config: dict
    secrets: dict
    http: Http
    state: dict = field(default_factory=dict)


class Connector:
    """Base class of a plugin. Subclasses set the class attributes and implement the methods."""

    manifest: Manifest
    # JSON Schema (object) of the configuration form. Properties with "secret": true are stored
    # encrypted and never shown again; "format": "uri" fields are addresses; "identity": true marks
    # fields that decide whose data the credentials open (tenant id, child CID, account, projects,
    # region): changing one requires the secrets again, like changing the address.
    config_schema: dict = {"type": "object", "properties": {}}
    operations: tuple[Operation, ...] = ()

    def origins(self, config: dict) -> list[str]:
        """Origins (scheme://host[:port]) this instance may call. Secrets are sent only there."""
        raise NotImplementedError

    def read_posts(self, config: dict) -> list[str]:
        """URL prefixes where POST is a read (token requests, search queries). Everything else must be GET."""
        return []

    def test_connection(self, ctx: Context) -> str:
        """Checks address and credentials with one cheap read; returns a short detail for the admin."""
        raise NotImplementedError

    def run(self, ctx: Context, operation: str, args: dict) -> list[Record]:
        raise NotImplementedError

    # Helpers ---------------------------------------------------------------------------

    def operation(self, name: str) -> Operation | None:
        return next((o for o in self.operations if o.name == name), None)


# --- Small helpers shared by plugins ------------------------------------------------------

def origin_of(url: str) -> str:
    """scheme://host[:port] of an address, lower-case."""
    m = re.match(r"^(https?)://([^/?#]+)", (url or "").strip(), re.IGNORECASE)
    if not m:
        raise ConnectorError("The address must start with http:// or https://.", retryable=False, public=True)
    return f"{m.group(1).lower()}://{m.group(2).lower()}"


def base_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def clip(value: Any, limit: int = 300) -> str:
    """A short, single-line string for a record field."""
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def status_error(product: str, status: int) -> ConnectorError:
    """A readable error for an HTTP status. The reply body is never included (it may echo secrets)."""
    hint = {400: "bad request", 401: "invalid credentials", 403: "access denied (check the API permissions)",
            404: "not found", 429: "rate limited by the product"}.get(status, "unexpected answer")
    return ConnectorError(f"{product} answered {status} ({hint})", retryable=status >= 500 or status == 429,
                          public=status in (401, 403, 429))
