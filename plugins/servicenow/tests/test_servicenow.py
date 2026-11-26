import re

import pytest

from app.connectors.contract import ConnectorError, Context
from mentis_servicenow import connector as sn

BASE = "https://acme.service-now.com"
ROW = {"sys_id": "a" * 32, "number": "INC0012345", "short_description": "Brute force on vpn-gw01", "description": "Many failed logins",
       "state": "In Progress", "priority": "2 - High", "assignment_group": "SOC L2", "assigned_to": "Mario Rossi",
       "cmdb_ci": "vpn-gw01", "sys_updated_on": "2026-11-26 10:00:00", "comments_and_work_notes": "2026-11-26 Mario: blocked IP",
       "u_customer_ref": "CR-77"}


def ctx(fake_http, routes, **config):
    cfg = {"instance_url": BASE, "auth": "basic", "username": "mentis", "table": "incident", "extra_fields": "u_customer_ref", **config}
    return Context(config=cfg, secrets={"password": "pw-secret", "client_secret": "cs", "api_key": "k"}, http=fake_http(routes))


def test_get_ticket_by_number(fake_http, ok):
    c = ctx(fake_http, [("GET", BASE + "/api/now/table/incident", ok(200, {"result": [ROW]}))])
    [r] = sn.run(c, "get_ticket", {"number": "inc0012345"})
    req = c.http.requests[0]
    assert req["params"]["sysparm_query"] == "number=INC0012345"
    assert req["params"]["sysparm_display_value"] == "true"
    assert "u_customer_ref" in req["params"]["sysparm_fields"]
    assert req["headers"]["Authorization"].startswith("Basic ")
    assert r.id == "INC0012345" and r.kind == "ticket"
    assert r.fields["State"] == "In Progress" and r.fields["Assignment group"] == "SOC L2" and r.fields["u_customer_ref"] == "CR-77"
    assert r.url == f"{BASE}/incident.do?sys_id={'a' * 32}"
    assert "blocked IP" in r.text


def test_prefix_picks_the_table(fake_http, ok):
    c = ctx(fake_http, [("GET", BASE + "/api/now/table/sn_si_incident", ok(200, {"result": []}))])
    assert sn.run(c, "get_ticket", {"number": "SIR0001234"}) == []


def test_search_strips_query_operators(fake_http, ok):
    c = ctx(fake_http, [("GET", BASE + "/api/now/table/incident", ok(200, {"result": [ROW]}))])
    sn.run(c, "search_tickets", {"query": "vpn^active=false"})
    q = c.http.requests[0]["params"]["sysparm_query"]
    assert q.startswith("active=true^short_descriptionLIKEvpn active false^ORdescriptionLIKE")
    assert q.count("^") == 3  # active, OR, ORDERBY: nothing injected


def test_match_pattern_finds_numbers():
    op = sn.operation("get_ticket")
    found = re.findall(op.match["number"], "check INC0012345 and SIR0000077, not XINC1")
    assert found == ["INC0012345", "SIR0000077"]


def test_oauth_token_cached_and_sent(fake_http, ok):
    routes = [("POST", BASE + "/oauth_token.do", ok(200, {"access_token": "tok", "expires_in": 1800})),
              ("GET", BASE + "/api/now/table/incident", ok(200, {"result": []}))]
    c = ctx(fake_http, routes, auth="oauth", client_id="cid")
    sn.run(c, "search_tickets", {"query": "phishing"})
    sn.run(c, "search_tickets", {"query": "phishing"})
    posts = [r for r in c.http.requests if r["method"] == "POST"]
    assert len(posts) == 1 and posts[0]["data"]["grant_type"] == "client_credentials"
    assert c.http.requests[-1]["headers"]["Authorization"] == "Bearer tok"
    assert BASE + "/oauth_token.do" in sn.read_posts(c.config)


def test_api_key_header(fake_http, ok):
    c = ctx(fake_http, [("GET", BASE, ok(200, {"result": []}))], auth="api_key")
    assert sn.test_connection(c).startswith("Connected")
    assert c.http.requests[0]["headers"]["x-sn-apikey"] == "k"


def test_errors_never_carry_the_body(fake_http, ok):
    c = ctx(fake_http, [("GET", BASE, ok(401, {"error": "pw-secret is wrong"}))])
    with pytest.raises(ConnectorError) as e:
        sn.run(c, "get_ticket", {"number": "INC0012345"})
    assert "401" in str(e.value) and "pw-secret" not in str(e.value) and e.value.public


def test_origins():
    assert sn.origins({"instance_url": "https://Acme.service-now.com/"}) == ["https://acme.service-now.com"]
