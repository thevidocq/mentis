"""Checks an instance configuration against the plugin's JSON Schema (the subset plugins use:
object of string / boolean / integer properties, enum, required, format "uri", maxLength) and
splits it into plain values and secrets."""

from app.connectors.contract import Connector

MAX_STRING = 2000


def properties(c: Connector) -> dict[str, dict]:
    return (c.config_schema or {}).get("properties", {})


def secret_keys(c: Connector) -> set[str]:
    return {k for k, p in properties(c).items() if p.get("secret")}


def identity_keys(c: Connector) -> set[str]:
    """Non-secret fields that, with the address, bind the stored secrets to one customer's data."""
    return {k for k, p in properties(c).items() if p.get("identity") and not p.get("secret")}


def rebinds(c: Connector, old: dict, new: dict) -> bool:
    """True when the new configuration would send the stored secrets to other data: another
    address (origin) or another identity field (tenant id, child CID, account, projects...)."""
    try:
        moved = {o.lower() for o in c.origins(old or {})} != {o.lower() for o in c.origins(new or {})}
    except Exception:  # noqa: BLE001 - an unreadable old address: treat as moved
        moved = True
    props = properties(c)

    def value(cfg: dict, k: str):
        v = (cfg or {}).get(k, props[k].get("default"))
        return v.strip().lower() if isinstance(v, str) else v

    return moved or any(value(old, k) != value(new, k) for k in identity_keys(c))


def public_schema(c: Connector) -> dict:
    """The schema as sent to the browser (it is not secret, but trimmed to what the form needs)."""
    return {"type": "object", "properties": properties(c), "required": list((c.config_schema or {}).get("required", []))}


def _problem(key: str, spec: dict, value) -> str | None:
    title = spec.get("title", key)
    kind = spec.get("type", "string")
    if kind == "boolean":
        return None if isinstance(value, bool) else f"{title}: must be true or false."
    if kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"{title}: must be a whole number."
        lo, hi = spec.get("minimum"), spec.get("maximum")
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            return f"{title}: out of range."
        return None
    if not isinstance(value, str):
        return f"{title}: must be text."
    if "\x00" in value or len(value) > spec.get("maxLength", MAX_STRING):
        return f"{title}: too long or invalid characters."
    if "enum" in spec and value not in spec["enum"]:
        return f"{title}: choose one of the listed values."
    if spec.get("format") == "uri" and value and not value.strip().lower().startswith(("https://", "http://")):
        return f"{title}: the address must start with https:// or http://."
    if spec.get("format") == "uri" and value and any(ch in value for ch in " \t\r\n"):
        return f"{title}: the address cannot contain spaces."
    if spec.get("format") == "uri" and value:
        from urllib.parse import urlsplit

        try:
            u = urlsplit(value)
        except ValueError:
            return f"{title}: invalid address."
        if u.query or u.fragment or "?" in value or "#" in value or "\\" in value or "@" in u.netloc or not u.hostname:
            return f"{title}: give the address only (no user name, ?, # or \\), e.g. https://acme.example.com."
    return None


def split(c: Connector, values: dict, stored_secrets: dict | None = None, *, require: bool = True) -> tuple[dict, dict, str | None]:
    """(config, secrets, problem). A secret omitted or None keeps the stored one; "" clears it.

    Unknown keys are dropped. Required fields (secrets included) must end up with a value, unless
    `require` is false (configuration import: secrets never travel).
    """
    props, secret = properties(c), secret_keys(c)
    config, secrets = {}, dict(stored_secrets or {})
    for key, spec in props.items():
        if key not in values or values[key] is None:
            if key not in secret and "default" in spec:
                config[key] = spec["default"]
            continue
        value = values[key]
        if isinstance(value, str):
            value = value.strip()
        problem = _problem(key, spec, value)
        if problem:
            return {}, {}, problem
        if spec.get("format") == "uri" and isinstance(value, str):
            value = value.rstrip("/")
        if key in secret:
            if value == "":
                secrets.pop(key, None)
            else:
                secrets[key] = value
        else:
            config[key] = value
    for key in (c.config_schema or {}).get("required", []) if require else []:
        have = secrets.get(key) if key in secret else config.get(key)
        if have in (None, ""):
            return {}, {}, f"{props.get(key, {}).get('title', key)}: required."
    return config, secrets, None
