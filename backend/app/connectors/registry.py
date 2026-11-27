"""Plugin discovery: Python entry points in the `mentis.connectors` group.

Each entry point loads a `Connector` instance (or class). Only packages named `mentis-*` (the
plugins of this repository) are loaded: an entry point added by any other installed package is
ignored, and two packages claiming the same name are both refused. Plugins whose contract version
differs from the core's are skipped with a warning. Tests replace the registry with `set_connectors`.
"""

import logging
from importlib.metadata import entry_points

from app.connectors.contract import CORE_API, KINDS, TYPES, Connector

_log = logging.getLogger("mentis.connectors")
GROUP = "mentis.connectors"

_override: dict[str, Connector] | None = None
_cache: dict[str, Connector] | None = None


def set_connectors(connectors: dict[str, Connector] | None) -> None:
    """Tests: use these connectors instead of the installed plugins (None = installed plugins)."""
    global _override, _cache
    _override, _cache = connectors, None


def _valid(name: str, c: Connector) -> bool:
    m = getattr(c, "manifest", None)
    if m is None or m.name != name:
        _log.warning("plugin %s skipped: its manifest name differs from the entry point", name)
        return False
    if m.core_api != CORE_API:
        _log.warning("plugin %s skipped: written for core API %s, this core is %s", name, m.core_api, CORE_API)
        return False
    if m.type not in TYPES or any(o.returns not in KINDS for o in c.operations):
        _log.warning("plugin %s skipped: unknown type or record kind", name)
        return False
    return True


def _ours(ep) -> bool:
    dist = getattr(ep, "dist", None)
    name = (getattr(dist, "name", "") or "").lower().replace("_", "-")
    if not name.startswith("mentis-"):
        _log.warning("entry point %s from package %r ignored: not a Mentis plugin package", ep.name, name)
        return False
    return True


def connectors() -> dict[str, Connector]:
    """Installed plugins by name, sorted by label."""
    global _cache
    if _override is not None:
        return dict(_override)
    if _cache is None:
        found: dict[str, Connector] = {}
        eps = [ep for ep in entry_points(group=GROUP) if _ours(ep)]
        names = [ep.name for ep in eps]
        for ep in eps:
            if names.count(ep.name) > 1:
                _log.warning("plugin %s skipped: claimed by more than one package", ep.name)
                continue
            try:
                obj = ep.load()
                c = obj() if isinstance(obj, type) else obj
            except Exception:  # noqa: BLE001 - one broken plugin must not stop the API
                _log.exception("plugin %s could not be loaded", ep.name)
                continue
            if _valid(ep.name, c):
                found[ep.name] = c
        _cache = dict(sorted(found.items(), key=lambda kv: kv[1].manifest.label.lower()))
    return dict(_cache)


def get(name: str) -> Connector | None:
    return connectors().get(name)
