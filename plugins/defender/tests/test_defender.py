import re

from app.connectors.contract import Context
from mentis_defender import connector as md

API = "https://api-eu.securitycenter.microsoft.com"
TENANT = "11111111-2222-3333-4444-555555555555"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
MID = "a" * 40
MACHINE = {"id": MID, "computerDnsName": "ws-042.acme.local", "osPlatform": "Windows11", "healthStatus": "Active", "riskScore": "High",
           "lastIpAddress": "10.1.2.3", "lastExternalIpAddress": "203.0.113.7", "machineTags": ["VIP"], "lastSeen": "2026-11-26T09:00:00Z"}
ALERT = {"id": "da637292082891366787_322230012", "title": "Suspicious PowerShell", "severity": "High", "status": "New",
         "computerDnsName": "ws-042.acme.local", "machineId": MID, "incidentId": 42, "mitreTechniques": ["T1059.001"],
         "alertCreationTime": "2026-11-26T08:00:00Z",
         "evidence": [{"entityType": "Ip", "ipAddress": "198.51.100.9"}, {"entityType": "File", "fileName": "evil.ps1", "sha256": "f" * 64}]}


def ctx(fake_http, routes):
    config = {"tenant_id": TENANT, "client_id": "app", "region": "eu"}
    return Context(config=config, secrets={"client_secret": "s3cret"}, http=fake_http(routes))


def token(ok):
    return ("POST", TOKEN_URL, ok(200, {"access_token": "tok", "expires_in": 3599}))


def test_device_with_ip_links(fake_http, ok):
    c = ctx(fake_http, [token(ok), ("GET", API + "/api/machines", ok(200, {"value": [MACHINE]}))])
    [r] = md.run(c, "get_device", {"host": "WS-042"})
    assert c.http.requests[0]["data"]["scope"] == "https://api.securitycenter.microsoft.com/.default"
    assert c.http.requests[1]["params"]["$filter"] == "startswith(computerDnsName,'ws-042')"
    assert r.url == f"https://security.microsoft.com/machines/{MID}/overview"
    assert r.links == {"IP 10.1.2.3": "https://security.microsoft.com/ip/10.1.2.3/overview",
                       "IP 203.0.113.7": "https://security.microsoft.com/ip/203.0.113.7/overview"}


def test_alert_with_evidence_and_links(fake_http, ok):
    c = ctx(fake_http, [token(ok), ("GET", API + "/api/alerts/", ok(200, ALERT))])
    [r] = md.run(c, "get_alert", {"alert_id": ALERT["id"]})
    assert c.http.requests[1]["params"] == {"$expand": "evidence"}
    assert r.url == f"https://security.microsoft.com/alerts/{ALERT['id']}"
    assert r.links["Incident 42"] == "https://security.microsoft.com/incidents/42"
    assert r.links["IP 198.51.100.9"].endswith("/ip/198.51.100.9/overview")
    assert "evil.ps1" in r.text and "T1059.001" in r.fields["Techniques"]


def test_device_alerts_skip_resolved(fake_http, ok):
    resolved = {**ALERT, "id": "da1", "status": "Resolved"}
    c = ctx(fake_http, [token(ok), ("GET", API + f"/api/machines/{MID}/alerts", ok(200, {"value": [resolved, ALERT]})),
                        ("GET", API + "/api/machines", ok(200, {"value": [MACHINE]}))])
    rows = md.run(c, "device_alerts", {"host": "ws-042"})
    assert [r.id for r in rows] == [ALERT["id"]]


def test_open_alerts_min_severity(fake_http, ok):
    low = {**ALERT, "id": "da2", "severity": "Low"}
    c = ctx(fake_http, [token(ok), ("GET", API + "/api/alerts", ok(200, {"value": [low, ALERT]}))])
    rows = md.run(c, "open_alerts", {"min_severity": "medium"})
    assert [r.id for r in rows] == [ALERT["id"]]
    assert c.http.requests[1]["params"]["$filter"].startswith("alertCreationTime ge ")


def test_ip_info(fake_http, ok):
    c = ctx(fake_http, [token(ok), ("GET", API + "/api/ips/203.0.113.7/stats", ok(200, {"orgPrevalence": "3"}))])
    [r] = md.run(c, "ip_info", {"ip": "203.0.113.7"})
    assert r.kind == "indicator" and r.url == "https://security.microsoft.com/ip/203.0.113.7/overview"


def test_origins_and_match():
    cfg = {"tenant_id": TENANT, "region": "eu"}
    assert md.origins(cfg) == ["https://login.microsoftonline.com", API]
    assert md.read_posts(cfg) == [TOKEN_URL]
    assert re.findall(md.operation("get_alert").match["alert_id"], f"alert {ALERT['id']} on host") == [ALERT["id"]]
