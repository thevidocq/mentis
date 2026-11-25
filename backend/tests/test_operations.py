import json
import socket
import socketserver
import threading
from datetime import timedelta

import pytest

from app.core import db as db_module
from app.models import AuditEvent, Chat, ChatMessage
from app.models.base import utcnow
from app.services import llm, syslog
from tests.conftest import login, new_client
from tests.fake_llm import FakeLLM
from tests.test_chat import _analyst, _provider, _setup
from tests.test_indexing import _tenant
from tests.test_tenants_users import _invite_and_accept


def _db():
    return next(db_module.get_db())


@pytest.fixture
def fake_llm():
    f = FakeLLM()
    llm.set_transport(f.transport())
    yield f
    llm.set_transport(None)


@pytest.fixture(autouse=True)
def reset_syslog():
    syslog.forwarder.reload(None)
    yield
    syslog.forwarder.reload({**syslog.DEFAULTS})


# --- Logs ----------------------------------------------------------------------

def test_logs_list_filter_and_export(super_admin):
    alfa = _tenant(super_admin, "Alfa")
    r = super_admin.get("/api/logs")
    assert r.status_code == 200
    page = r.json()
    assert page["total"] >= 3 and page["items"][0]["action"] == "tenant.created"
    assert page["items"][0]["tenant"] == "Alfa"
    only = super_admin.get("/api/logs", params={"tenant_id": alfa["id"]}).json()
    assert {i["action"] for i in only["items"]} == {"tenant.created"}
    assert super_admin.get("/api/logs", params={"action": "auth."}).json()["total"] >= 2
    assert super_admin.get("/api/logs", params={"q": "admin@example"}).json()["total"] >= 1
    assert super_admin.get("/api/logs", params={"level": "bogus"}).status_code == 422
    assert "auth.login.success" in super_admin.get("/api/logs/actions").json()
    csv = super_admin.get("/api/logs/export", params={"kind": "audit"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert csv.text.splitlines()[0].startswith("time_utc,kind,level,action")
    assert "tenant.created" in csv.text
    assert super_admin.get("/api/logs/summary").json()["info"] >= 1


def test_logs_are_super_admin_only(super_admin):
    alfa = _tenant(super_admin, "Alfa")
    an = _analyst(super_admin)
    assert an.get("/api/logs").status_code == 403
    _invite_and_accept(super_admin, "ta@example.com", "tenant_admin", alfa["id"])
    ta = new_client(super_admin.app)
    login(ta, "ta@example.com")
    assert ta.get("/api/logs").status_code == 403
    assert ta.get("/api/logs/export").status_code == 403


def test_csv_export_neutralises_formulas(super_admin):
    _tenant(super_admin, "=HYPERLINK(1)")
    assert "'=HYPERLINK(1)" in super_admin.get("/api/logs/export").text


# --- Syslog --------------------------------------------------------------------

def test_syslog_format():
    e = AuditEvent(ts=utcnow(), kind="audit", level="warning", action="tenant.deleted", actor_email="a@b.c",
                   target='Alfa "x"]', ip="1.2.3.4", detail={"n": 1})
    line = syslog.format_event(e, hostname="host")
    assert line.startswith("<108>1 ")  # facility 13 (log audit) * 8 + severity 4 (warning)
    assert ' host mentis - tenant.deleted [mentis@32473 kind="audit" level="warning" actor="a@b.c"' in line
    assert 'target="Alfa \\"x\\"\\]"' in line
    assert line.endswith('"detail":{"n":1}}')


class _Collector(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def test_syslog_forwarding_tcp_and_test_button(super_admin):
    received: list[bytes] = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            while chunk := self.request.recv(65536):
                received.append(chunk)

    srv = _Collector(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        assert super_admin.put("/api/platform/syslog", json={"enabled": True, "host": "", "port": port, "protocol": "tcp"}).status_code == 422
        assert super_admin.put("/api/platform/syslog", json={"enabled": True, "host": "127.0.0.1", "port": port, "protocol": "smoke"}).status_code == 422
        r = super_admin.put("/api/platform/syslog", json={"enabled": True, "host": "127.0.0.1", "port": port, "protocol": "tcp"})
        assert r.status_code == 200, r.text
        _tenant(super_admin, "Alfa")
        assert super_admin.post("/api/platform/syslog/test").json()["ok"] is True
        syslog.forwarder.flush()
        data = b"".join(received).decode()
        assert "tenant.created" in data and "syslog.test" in data
        # RFC 6587 octet counting: "<len> <msg>"
        first = data.split(" ", 1)
        assert first[0].isdigit() and first[1].startswith("<")
    finally:
        srv.shutdown()
        srv.server_close()


def test_syslog_udp_and_unreachable(super_admin):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(2)
    port = s.getsockname()[1]
    super_admin.put("/api/platform/syslog", json={"enabled": True, "host": "127.0.0.1", "port": port, "protocol": "udp"})
    r = super_admin.post("/api/platform/syslog/test").json()
    assert r["ok"] and "UDP" in r["message"]
    got = b""
    while b"syslog.test" not in got:
        got += s.recv(65536)  # the settings change itself is forwarded first
    s.close()
    # A TCP collector that is down: the test says so, requests are not slowed down.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead = probe.getsockname()[1]
    super_admin.put("/api/platform/syslog", json={"enabled": True, "host": "127.0.0.1", "port": dead, "protocol": "tcp"})
    assert super_admin.post("/api/platform/syslog/test").json()["ok"] is False
    assert super_admin.get("/api/tenants").status_code == 200


# --- Retention -----------------------------------------------------------------

def test_retention_settings_and_purge(super_admin):
    assert super_admin.get("/api/platform/retention").json()["chats_days"] == 365
    assert super_admin.put("/api/platform/retention", json={"chats_days": -1, "logs_days": 10}).status_code == 422
    assert super_admin.put("/api/platform/retention", json={"chats_days": 30, "logs_days": 90}).status_code == 200
    db = _db()
    admin_id = db.scalar(__import__("sqlalchemy").select(AuditEvent.actor_user_id).where(AuditEvent.actor_user_id.is_not(None)))
    old = utcnow() - timedelta(days=100)
    chat_old = Chat(user_id=admin_id, title="old", updated_at=old)
    chat_new = Chat(user_id=admin_id, title="new")
    db.add_all([chat_old, chat_new])
    db.flush()
    db.add_all([ChatMessage(chat_id=chat_old.id, role="user", content="x"), ChatMessage(chat_id=chat_new.id, role="user", content="y")])
    db.add(AuditEvent(ts=old, kind="audit", level="info", action="old.event", detail={}))
    db.commit()
    r = super_admin.post("/api/platform/retention/purge").json()
    assert r == {"chats": 1, "messages": 1, "log_events": 1}
    db = _db()
    assert [c.title for c in db.query(Chat)] == ["new"]
    cfg = super_admin.get("/api/platform/retention").json()
    assert cfg["last_result"] == r and cfg["last_purge"]
    # 0 = keep forever
    super_admin.put("/api/platform/retention", json={"chats_days": 0, "logs_days": 0})
    assert super_admin.post("/api/platform/retention/purge").json() == {"chats": 0, "messages": 0, "log_events": 0}


def test_daily_purge_runs_once_across_workers(super_admin, monkeypatch):
    from app.worker import maintenance

    taken = set()

    class FakeRedis:
        def set(self, key, value, nx, ex):
            if key in taken:
                return False
            taken.add(key)
            return True

    monkeypatch.setattr(maintenance, "redis_connection", lambda: FakeRedis())
    assert maintenance.run_purge_once() == {"chats": 0, "messages": 0, "log_events": 0}
    assert maintenance.run_purge_once() is None
    assert "retention.purged" in super_admin.get("/api/logs/actions").json()


# --- Usage ---------------------------------------------------------------------

def test_usage_per_customer_with_cost(super_admin, fake_llm):
    p = _provider(super_admin, options={"price_in": 1.0, "price_out": 5.0})
    assert super_admin.put(f"/api/llm/providers/{p['id']}", json={**p, "options": {"price_in": -1}}).status_code == 422
    alfa, beta = _setup(super_admin)
    an = _analyst(super_admin)
    an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"})
    an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "zzz qqq xyzzy"})
    an.post("/api/chats", json={"tenant_id": None, "message": "brute force escalation"})
    u = super_admin.get("/api/usage", params={"days": 7}).json()
    rows = {(r["customer"], r["provider"]): r for r in u["rows"]}
    a = rows[("Alfa", "Claude")]
    assert a["questions"] == 1 and a["input_tokens"] == 100 and a["output_tokens"] == 20
    assert a["cost_usd"] == pytest.approx(100 / 1e6 * 1 + 20 / 1e6 * 5)
    assert rows[("Alfa", "—")]["not_found"] == 1
    assert ("All customers", "Claude") in rows
    assert u["totals"]["questions"] == 3
    assert an.get("/api/usage").status_code == 403
    _invite_and_accept(super_admin, "ta@example.com", "tenant_admin", beta["id"])
    ta = new_client(super_admin.app)
    login(ta, "ta@example.com")
    assert ta.get("/api/usage").json()["rows"] == []  # Beta has no questions; Alfa is not visible


# --- Configuration import/export -------------------------------------------------

def test_config_export_has_no_secrets_and_imports_elsewhere(super_admin, fake_llm):
    p1 = _provider(super_admin)
    p2 = _provider(super_admin, name="Ollama", kind="openai_chat", base_url="http://ollama:11434/v1", model="llama3.1")
    alfa = _tenant(super_admin, "Alfa")
    super_admin.put(f"/api/tenants/{alfa['id']}/llm", json={"provider_id": p2["id"], "fallback_id": p1["id"]})
    super_admin.patch(f"/api/tenants/{alfa['id']}", json={"settings": {"suggested_followups": False}})
    super_admin.put("/api/platform/smtp", json={"host": "smtp.example.com", "port": 587, "security": "starttls",
                                                 "username": "u", "password": "secret-pw", "from_address": "m@example.com"})
    super_admin.put("/api/platform/retention", json={"chats_days": 90, "logs_days": 180})
    r = super_admin.get("/api/platform/config/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    text = r.text
    assert "secret-pw" not in text and "sk-test" not in text and "_enc" not in text
    data = json.loads(text)
    alfa_cfg = next(t for t in data["tenants"] if t["name"] == "Alfa")
    assert alfa_cfg["llm"] == "Ollama" and alfa_cfg["llm_fallback"] == "Claude" and alfa_cfg["settings"]["suggested_followups"] is False

    # Simulate another installation: delete what the file describes, then import.
    super_admin.request("DELETE", f"/api/tenants/{alfa['id']}", json={"confirm_name": "Alfa"})
    super_admin.delete(f"/api/llm/providers/{p2['id']}")
    super_admin.put("/api/platform/retention", json={"chats_days": 365, "logs_days": 365})
    files = {"file": ("cfg.json", json.dumps(data).encode(), "application/json")}
    plan = super_admin.post("/api/platform/config/import", files=files).json()
    assert plan["applied"] is False
    assert "Create tenant Alfa (onboarding)" in plan["changes"] or "Create tenant Alfa (active)" in plan["changes"]
    assert any("Add AI provider Ollama" in c for c in plan["changes"])
    assert any("retention" in c for c in plan["changes"])
    assert not any(t["name"] == "Alfa" for t in super_admin.get("/api/tenants").json())  # dry run changed nothing
    done = super_admin.post("/api/platform/config/import", params={"apply": "true"}, files=files).json()
    assert done["applied"] is True
    alfa2 = next(t for t in super_admin.get("/api/tenants").json() if t["name"] == "Alfa")
    assert alfa2["settings"]["suggested_followups"] is False
    llm_choice = super_admin.get(f"/api/tenants/{alfa2['id']}/llm").json()
    names = {p["id"]: p["name"] for p in super_admin.get("/api/llm/providers").json()}
    assert names[llm_choice["provider_id"]] == "Ollama" and names[llm_choice["fallback_id"]] == "Claude"
    assert super_admin.get("/api/platform/retention").json()["chats_days"] == 90
    assert super_admin.get("/api/platform/smtp").json()["password_set"] is True  # kept, never overwritten
    # Importing again changes nothing.
    assert super_admin.post("/api/platform/config/import", files=files).json()["changes"] == []


def test_config_import_rejects_bad_files(super_admin):
    bad = [b"not json", json.dumps({"format": "other"}).encode(),
           json.dumps({"format": "mentis-config/1", "tenants": [{"name": "X", "settings": {"evil": True}}]}).encode(),
           json.dumps({"format": "mentis-config/1", "llm_providers": [{"name": "x", "kind": "nope", "base_url": "u", "model": "m"}]}).encode()]
    for raw in bad:
        r = super_admin.post("/api/platform/config/import", files={"file": ("c.json", raw, "application/json")})
        assert r.status_code == 422, raw
    an = _analyst(super_admin)
    assert an.get("/api/platform/config/export").status_code == 403


def test_importing_own_export_changes_nothing(super_admin):
    _tenant(super_admin, "Alfa")
    raw = super_admin.get("/api/platform/config/export").content
    r = super_admin.post("/api/platform/config/import", files={"file": ("c.json", raw, "application/json")})
    assert r.json()["changes"] == []
