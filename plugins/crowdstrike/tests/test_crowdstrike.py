import re

import pytest

from app.connectors.contract import ConnectorError, Context
from mentis_crowdstrike import connector as cs

API = "https://api.eu-1.crowdstrike.com"
AID = "b" * 32
CID = "c" * 32
ALERT_ID = f"{CID}:ind:{AID}:12345-10305-567"
DEVICE = {"device_id": AID, "hostname": "WS-042", "platform_name": "Windows", "os_version": "Windows 11", "status": "contained",
          "last_seen": "2026-11-26T09:00:00Z", "local_ip": "10.1.2.3", "external_ip": "203.0.113.7", "agent_version": "7.20"}
ALERT = {"composite_id": ALERT_ID, "display_name": "Credential dumping", "severity_name": "High", "status": "new",
         "device": {"hostname": "WS-042", "device_id": AID}, "technique_id": "T1003", "technique": "OS Credential Dumping",
         "cmdline": "procdump -ma lsass.exe", "falcon_host_link": f"https://falcon.eu-1.crowdstrike.com/activity-v2/detections/{ALERT_ID}"}


def ctx(fake_http, routes, **cfg):
    config = {"cloud": "eu-1", "client_id": "cid", "member_cid": "", **cfg}
    return Context(config=config, secrets={"client_secret": "s3cret"}, http=fake_http(routes))


def token(ok):
    return ("POST", API + "/oauth2/token", ok(201, {"access_token": "tok", "expires_in": 1799}))


def test_host(fake_http, ok):
    c = ctx(fake_http, [token(ok), ("GET", API + "/devices/queries/devices/v1", ok(200, {"resources": [AID]})),
                        ("GET", API + "/devices/entities/devices/v2", ok(200, {"resources": [DEVICE]}))])
    [r] = cs.run(c, "get_host", {"host": "ws-042"})
    q = c.http.requests[1]
    assert q["params"]["filter"] == "hostname:'ws-042'" and q["headers"]["Authorization"] == "Bearer tok"
    assert c.http.requests[2]["params"]["ids"] == [AID]
    assert r.kind == "device" and r.id == "WS-042" and r.fields["Containment"].startswith("contained")
    assert r.url == f"https://falcon.eu-1.crowdstrike.com/hosts/hosts/host/{AID}"


def test_alerts_of_host_and_member_cid(fake_http, ok):
    c = ctx(fake_http, [token(ok), ("GET", API + "/alerts/queries/alerts/v2", ok(200, {"resources": [ALERT_ID]})),
                        ("POST", API + "/alerts/entities/alerts/v2", ok(200, {"resources": [ALERT]}))], member_cid="d" * 32)
    [r] = cs.run(c, "host_alerts", {"host": "WS-042"})
    assert c.http.requests[0]["data"]["member_cid"] == "d" * 32
    assert c.http.requests[1]["params"]["filter"] == "device.hostname:'WS-042'+status:!'closed'"
    assert c.http.requests[2]["json"] == {"composite_ids": [ALERT_ID]}
    assert r.fields["Technique"] == "T1003 OS Credential Dumping" and r.url == ALERT["falcon_host_link"]
    assert list(r.links.values()) == [f"https://falcon.eu-1.crowdstrike.com/hosts/hosts/host/{AID}"]
    assert API + "/alerts/entities/alerts/v2" in cs.read_posts(c.config)


def test_open_alerts_severity(fake_http, ok):
    c = ctx(fake_http, [token(ok), ("GET", API + "/alerts/queries/alerts/v2", ok(200, {"resources": []}))])
    assert cs.run(c, "open_alerts", {"min_severity": "high"}) == []
    assert c.http.requests[1]["params"]["filter"] == "status:['new','in_progress']+severity:>=60"


def test_alert_id_match_and_foreign_link_dropped(fake_http, ok):
    assert re.findall(cs.operation("get_alert").match["alert_id"], f"see {ALERT_ID} now") == [ALERT_ID]
    bad = {**ALERT, "falcon_host_link": "https://evil.example.com/x"}
    c = ctx(fake_http, [token(ok), ("POST", API + "/alerts/entities/alerts/v2", ok(200, {"resources": [bad]}))])
    [r] = cs.run(c, "get_alert", {"alert_id": ALERT_ID})
    assert r.url is None


def test_new_token_after_401(fake_http, ok):
    answers = iter([ok(401, {}), ok(200, {"resources": []})])
    c = ctx(fake_http, [token(ok), ("GET", API + "/devices/queries/devices/v1", lambda req: next(answers))])
    assert cs.run(c, "get_host", {"host": "ws-1"}) == []
    assert [r["method"] for r in c.http.requests] == ["POST", "GET", "POST", "GET"]


def test_bad_credentials(fake_http, ok):
    c = ctx(fake_http, [("POST", API + "/oauth2/token", ok(403, {"errors": ["s3cret"]}))])
    with pytest.raises(ConnectorError) as e:
        cs.test_connection(c)
    assert "403" in str(e.value) and "s3cret" not in str(e.value)
