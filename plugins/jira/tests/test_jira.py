import re

from app.connectors.contract import Context
from mentis_jira import adf_text
from mentis_jira import connector as jira

CLOUD = "https://acme.atlassian.net"
DC = "https://jira.acme.local"
ADF = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "EDR alert on "},
                                                                                   {"type": "text", "text": "ws-042"}]}]}
ISSUE = {"key": "SOC-12", "fields": {"summary": "Malware on ws-042", "status": {"name": "In Progress"}, "priority": {"name": "High"},
                                     "assignee": {"displayName": "Anna Bianchi"}, "labels": ["edr", "malware"], "description": ADF,
                                     "updated": "2026-11-26T09:00:00.000+0100", "customfield_10010": {"value": "Gold"},
                                     "comment": {"comments": [{"author": {"displayName": "Anna"}, "created": "2026-11-26T09:10",
                                                               "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "isolated"}]}]}}]}}}


def ctx(fake_http, routes, **cfg):
    config = {"site_url": CLOUD, "deployment": "cloud", "email": "soc@acme.com", "projects": "", "extra_fields": "customfield_10010", **cfg}
    return Context(config=config, secrets={"api_token": "tok-secret", "pat": "pat-secret"}, http=fake_http(routes))


def test_get_issue_cloud(fake_http, ok):
    c = ctx(fake_http, [("GET", CLOUD + "/rest/api/3/issue/SOC-12", ok(200, ISSUE))])
    [r] = jira.run(c, "get_issue", {"key": "soc-12"})
    assert c.http.requests[0]["headers"]["Authorization"].startswith("Basic ")
    assert r.id == "SOC-12" and r.url == CLOUD + "/browse/SOC-12"
    assert r.fields["Status"] == "In Progress" and r.fields["Assignee"] == "Anna Bianchi" and r.fields["customfield_10010"] == "Gold"
    assert "EDR alert on ws-042" in r.text and "isolated" in r.text


def test_data_center_uses_v2_and_pat(fake_http, ok):
    c = ctx(fake_http, [("GET", DC + "/rest/api/2/search", ok(200, {"issues": [ISSUE]}))], site_url=DC, deployment="datacenter")
    [r] = jira.run(c, "search_issues", {"query": 'phish "OR 1=1'})
    req = c.http.requests[0]
    assert req["headers"]["Authorization"] == "Bearer pat-secret"
    assert req["params"]["jql"] == 'text ~ "phish OR 1 1" AND statusCategory != Done ORDER BY updated DESC'


def test_projects_limit_keys_and_searches(fake_http, ok):
    c = ctx(fake_http, [("GET", CLOUD + "/rest/api/3/search/jql", ok(200, {"issues": []}))], projects="soc, sec")
    assert jira.run(c, "get_issue", {"key": "HR-1"}) == []
    assert c.http.requests == []
    jira.run(c, "issues_for_host", {"host": "ws-042"})
    jql = c.http.requests[0]["params"]["jql"]
    assert jql.startswith('text ~ "\\"ws-042\\"" AND statusCategory != Done') and "project in (SOC, SEC)" in jql


def test_missing_issue_is_nothing_found(fake_http, ok):
    c = ctx(fake_http, [("GET", CLOUD, ok(404, {}))])
    assert jira.run(c, "get_issue", {"key": "SOC-99"}) == []


def test_key_pattern_skips_standards_and_other_ids():
    m = jira.operation("get_issue").match["key"]
    text = "SOC-12 and CVE-2024-1234, SHA-256, WB-14-20190709-00003, INC0012345 and SEC-7"
    assert re.findall(m, text) == ["SOC-12", "SEC-7"]


def test_adf_text():
    assert adf_text(ADF) == "EDR alert on ws-042"
