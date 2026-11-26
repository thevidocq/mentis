import re

from app.connectors.contract import Context
from mentis_trendmicro_visionone import connector as v1

API = "https://api.eu.xdr.trendmicro.com"
ALERT = {"id": "WB-14-20261126-00003", "model": "Possible Credential Dumping", "severity": "high", "score": 70, "status": "Open",
         "createdDateTime": "2026-11-26T08:00:00Z", "workbenchLink": "https://portal.eu.xdr.trendmicro.com/index.html#/workbench?workbenchId=WB-14-20261126-00003",
         "impactScope": {"entities": [{"entityType": "host", "entityValue": {"name": "WS-042.acme.local", "ips": ["10.1.2.3"]}}]},
         "indicators": [{"type": "fileSha256", "value": "f" * 64}], "matchedRules": [{"name": "Dump LSASS"}]}
ENDPOINT = {"agentGuid": "g-1", "endpointName": {"value": "WS-042"}, "type": "desktop", "os": {"name": "Windows 11"},
            "lastUsedIp": "10.1.2.3", "edrSensor": {"status": "enabled", "connectivity": "connected", "lastConnectedDateTime": "2026-11-26T09:00:00Z"}}


def ctx(fake_http, routes):
    return Context(config={"region": "eu"}, secrets={"api_key": "key-secret"}, http=fake_http(routes))


def test_endpoint_by_name(fake_http, ok):
    c = ctx(fake_http, [("GET", API + "/v3.0/endpointSecurity/endpoints", ok(200, {"items": [ENDPOINT]}))])
    [r] = v1.run(c, "get_endpoint", {"host": "WS-042"})
    req = c.http.requests[0]
    assert req["headers"]["TMV1-Filter"] == "endpointName eq 'WS-042'" and req["headers"]["Authorization"] == "Bearer key-secret"
    assert r.id == "WS-042" and "connected" in r.fields["Sensor (EDR)"]


def test_alert_by_id_and_workbench_link(fake_http, ok):
    c = ctx(fake_http, [("GET", API + "/v3.0/workbench/alerts/WB-14-20261126-00003", ok(200, ALERT))])
    [r] = v1.run(c, "get_alert", {"alert_id": "WB-14-20261126-00003"})
    assert r.url == ALERT["workbenchLink"] and r.fields["Endpoints"] == "WS-042.acme.local" and "f" * 64 in r.text


def test_foreign_workbench_link_dropped(fake_http, ok):
    c = ctx(fake_http, [("GET", API + "/v3.0/workbench/alerts/", ok(200, {**ALERT, "workbenchLink": "https://evil.example.com/"}))])
    [r] = v1.run(c, "get_alert", {"alert_id": "WB-14-20261126-00003"})
    assert r.url is None


def test_endpoint_alerts_match_short_name(fake_http, ok):
    other = {**ALERT, "id": "WB-1-20261126-00001", "impactScope": {"entities": [{"entityType": "host", "entityValue": {"name": "srv-9"}}]}}
    c = ctx(fake_http, [("GET", API + "/v3.0/workbench/alerts", ok(200, {"items": [other, ALERT]}))])
    rows = v1.run(c, "endpoint_alerts", {"host": "ws-042"})
    assert [r.id for r in rows] == [ALERT["id"]]
    assert c.http.requests[0]["params"]["orderBy"] == "createdDateTime desc"


def test_open_alerts_filter(fake_http, ok):
    closed = {**ALERT, "id": "WB-1-20261126-00002", "status": "Closed"}
    low = {**ALERT, "id": "WB-1-20261126-00004", "severity": "low"}
    c = ctx(fake_http, [("GET", API + "/v3.0/workbench/alerts", ok(200, {"items": [closed, low, ALERT]}))])
    assert [r.id for r in v1.run(c, "open_alerts", {"min_severity": "high"})] == [ALERT["id"]]


def test_match_and_origins():
    assert re.findall(v1.operation("get_alert").match["alert_id"], "WB-14-20261126-00003 and SOC-1") == ["WB-14-20261126-00003"]
    assert v1.origins({"region": "jp"}) == ["https://api.xdr.trendmicro.co.jp"]
