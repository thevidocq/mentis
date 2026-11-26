"""Forwarding log events to a SIEM over syslog (RFC 5424; UDP, TCP or TLS with RFC 6587 octet counting).

Sending happens on a background thread with a bounded queue, so a slow or unreachable
collector never delays a request. If the queue is full, events are dropped and counted.
"""

import json
import logging
import os
import queue
import socket
import ssl
import threading
import time
from datetime import UTC

from sqlalchemy.orm import Session

from app.models import AuditEvent, PlatformSetting

KEY = "syslog"
PROTOCOLS = ("udp", "tcp", "tls")
DEFAULTS = {"enabled": False, "host": "", "port": 514, "protocol": "udp", "verify_tls": True, "app_name": "mentis"}
_SEVERITY = {"error": 3, "warning": 4, "info": 6}
_FACILITY = {"audit": 13, "system": 1}  # log audit, user-level

_log = logging.getLogger("mentis.syslog")


def get_config(db: Session) -> dict:
    row = db.get(PlatformSetting, KEY)
    return {**DEFAULTS, **(row.value if row else {})}


def save_config(db: Session, data: dict) -> dict:
    cfg = {**get_config(db), **{k: v for k, v in data.items() if k in DEFAULTS}}
    row = db.get(PlatformSetting, KEY)
    if row is None:
        db.add(PlatformSetting(key=KEY, value=cfg))
    else:
        row.value = cfg
    db.commit()
    forwarder.reload(cfg)
    return cfg


def _sd(value) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("]", "\\]")


def format_event(e: AuditEvent, app_name: str = "mentis", hostname: str | None = None) -> str:
    pri = _FACILITY.get(e.kind, 1) * 8 + _SEVERITY.get(e.level, 6)
    ts = e.ts.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    params = {"kind": e.kind, "level": e.level, "actor": e.actor_email or "-", "tenant": e.tenant_id or "-",
              "target": e.target or "-", "ip": e.ip or "-"}
    sd = "[mentis@32473 " + " ".join(f'{k}="{_sd(v)}"' for k, v in params.items()) + "]"
    host = (hostname or socket.gethostname())[:255]
    msg = json.dumps({"action": e.action, **params, "detail": e.detail or {}}, default=str, separators=(",", ":"))
    return f"<{pri}>1 {ts} {host} {app_name} - {e.action} {sd} {msg}"


def send_one(cfg: dict, line: str, timeout: float = 3) -> None:
    """Send one message synchronously. Raises OSError on failure (used by the Test button)."""
    data = line.encode("utf-8")
    host, port = cfg["host"], int(cfg["port"])
    if cfg["protocol"] == "udp":
        # Cut long datagrams on a character boundary: half a UTF-8 sequence is rejected by strict parsers.
        data = data[:8000].decode("utf-8", "ignore").encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(data, (host, port))
        return
    frame = f"{len(data)} ".encode() + data
    raw = socket.create_connection((host, port), timeout=timeout)
    try:
        if cfg["protocol"] == "tls":
            ctx = ssl.create_default_context()
            if not cfg.get("verify_tls", True):
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            raw = ctx.wrap_socket(raw, server_hostname=host)
        raw.sendall(frame)
    finally:
        raw.close()


class Forwarder:
    """Process-wide sender. Keeps one TCP/TLS connection open and reconnects when it drops."""

    def __init__(self):
        self._q: queue.Queue[str] = queue.Queue(maxsize=10000)
        self._cfg: dict | None = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.dropped = 0
        self.sent = 0
        self.last_error: str | None = None
        # The worker forks one child per job, and the child exits without running atexit
        # handlers: a background thread there could lose events. Children send synchronously.
        self.synchronous = False
        os.register_at_fork(after_in_child=self._after_fork)

    def _after_fork(self) -> None:
        self._q = queue.Queue(maxsize=10000)
        self._thread = None
        self._lock = threading.Lock()
        self.synchronous = True

    def reload(self, cfg: dict | None) -> None:
        with self._lock:
            self._cfg, self._loaded_at = cfg, time.monotonic()

    def config(self, db: Session) -> dict:
        # Other processes (worker, other API replicas) pick up changes within a minute.
        if self._cfg is None or time.monotonic() - self._loaded_at > 60:
            try:
                self.reload(get_config(db))
            except Exception:  # noqa: BLE001 - never let forwarding break the caller
                return self._cfg or DEFAULTS
        return self._cfg

    def submit(self, db: Session, e: AuditEvent) -> None:
        cfg = self.config(db)
        if not (cfg.get("enabled") and cfg.get("host")):
            return
        if self.synchronous:
            try:
                send_one(cfg, format_event(e, cfg.get("app_name") or "mentis"), timeout=2)
                self.sent += 1
            except (OSError, ValueError) as ex:
                self.dropped += 1
                self.last_error = f"{ex.__class__.__name__}: {ex}"[:200]
            return
        try:
            self._q.put_nowait(format_event(e, cfg.get("app_name") or "mentis"))
        except queue.Full:
            self.dropped += 1
            return
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="syslog", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        conn, conn_cfg = None, None
        while True:
            line = self._q.get()
            cfg = self._cfg or DEFAULTS
            try:
                if cfg["protocol"] == "udp":
                    send_one(cfg, line)
                else:
                    if conn is None or conn_cfg != cfg:
                        if conn:
                            conn.close()
                        conn, conn_cfg = self._connect(cfg), dict(cfg)
                    data = line.encode("utf-8")
                    conn.sendall(f"{len(data)} ".encode() + data)
                self.sent += 1
                self.last_error = None
            # Not only OSError: a host name IDNA cannot encode raises UnicodeError, and an exception
            # escaping here would end the thread while submit() keeps queueing.
            except Exception as ex:  # noqa: BLE001
                self.dropped += 1
                self.last_error = f"{ex.__class__.__name__}: {ex}"[:200]
                if conn:
                    conn.close()
                conn = None
                time.sleep(1)  # do not spin on a dead collector

    @staticmethod
    def _connect(cfg: dict):
        raw = socket.create_connection((cfg["host"], int(cfg["port"])), timeout=3)
        if cfg["protocol"] == "tls":
            ctx = ssl.create_default_context()
            if not cfg.get("verify_tls", True):
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            raw = ctx.wrap_socket(raw, server_hostname=cfg["host"])
        return raw

    def flush(self, timeout: float = 2) -> None:
        """Tests: wait until the queue is empty."""
        end = time.monotonic() + timeout
        while not self._q.empty() and time.monotonic() < end:
            time.sleep(0.02)
        time.sleep(0.05)


forwarder = Forwarder()
