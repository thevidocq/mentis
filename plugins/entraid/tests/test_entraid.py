import re

from app.connectors.contract import Context
from mentis_entraid import connector as entra

TENANT = "11111111-2222-3333-4444-555555555555"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
G = "https://graph.microsoft.com/v1.0"
UID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
USER = {"id": UID, "displayName": "Mario Rossi", "userPrincipalName": "mario.rossi@acme.com", "mail": "mario.rossi@acme.com",
        "accountEnabled": False, "department": "Finance", "lastPasswordChangeDateTime": "2026-11-20T08:00:00Z"}


def ctx(fake_http, routes):
    return Context(config={"tenant_id": TENANT, "client_id": "app"}, secrets={"client_secret": "s3cret"}, http=fake_http(routes))


def token(ok):
    return ("POST", TOKEN_URL, ok(200, {"access_token": "tok", "expires_in": 3599}))


def test_user_with_mfa_risk_and_last_signin(fake_http, ok):
    c = ctx(fake_http, [
        token(ok),
        ("GET", f"{G}/users/{UID}/authentication/methods", ok(200, {"value": [
            {"@odata.type": "#microsoft.graph.passwordAuthenticationMethod"},
            {"@odata.type": "#microsoft.graph.microsoftAuthenticatorAuthenticationMethod"}]})),
        ("GET", f"{G}/users/{UID}", ok(200, {"signInActivity": {"lastSignInDateTime": "2026-11-26T07:00:00Z"}})),
        ("GET", f"{G}/identityProtection/riskyUsers/{UID}", ok(200, {"riskLevel": "high", "riskState": "atRisk"})),
        ("GET", f"{G}/users/mario.rossi@acme.com", ok(200, USER)),
    ])
    [r] = entra.run(c, "get_user", {"user": "mario.rossi@acme.com"})
    assert c.http.requests[0]["data"]["scope"] == "https://graph.microsoft.com/.default"
    assert r.kind == "user" and r.id == "mario.rossi@acme.com"
    assert r.fields["Account"].startswith("blocked") and r.fields["MFA methods"] == "Authenticator app"
    assert r.fields["Risk"] == "high · atRisk" and r.fields["Last sign-in"] == "2026-11-26T07:00:00Z"
    assert r.url.endswith(f"/userId/{UID}") and r.url.startswith("https://entra.microsoft.com/")


def test_missing_licence_or_permission_leaves_the_part_out(fake_http, ok):
    c = ctx(fake_http, [
        token(ok),
        ("GET", f"{G}/users/{UID}/authentication/methods", ok(403, {})),
        ("GET", f"{G}/users/{UID}", ok(403, {})),
        ("GET", f"{G}/identityProtection/riskyUsers/{UID}", ok(403, {})),
        ("GET", f"{G}/users/mario.rossi@acme.com", ok(200, USER)),
    ])
    [r] = entra.run(c, "get_user", {"user": "mario.rossi@acme.com"})
    assert "MFA methods" not in r.fields and "Risk" not in r.fields and "Last sign-in" not in r.fields
    assert r.fields["Department"] == "Finance"


def test_email_alias_and_display_name(fake_http, ok):
    c = ctx(fake_http, [token(ok), ("GET", f"{G}/users/m.rossi@acme.com", ok(404, {})),
                        ("GET", f"{G}/users/{UID}", ok(403, {})), ("GET", f"{G}/identityProtection", ok(404, {})),
                        ("GET", f"{G}/users", ok(200, {"value": [USER]}))])
    [r] = entra.run(c, "get_user", {"user": "m.rossi@acme.com"})
    alias = next(q for q in c.http.requests if q["params"].get("$filter", "").startswith("mail eq"))
    assert "proxyAddresses/any(p:p eq 'smtp:m.rossi@acme.com')" in alias["params"]["$filter"]
    assert alias["headers"]["ConsistencyLevel"] == "eventual"
    c2 = ctx(fake_http, [token(ok), ("GET", f"{G}/users", ok(200, {"value": []}))])
    assert entra.run(c2, "get_user", {"user": "D'Angelo"}) == []
    assert c2.http.requests[1]["params"]["$filter"] == "startswith(displayName,'D''Angelo')"


def test_signins(fake_http, ok):
    rows = [{"userId": UID, "createdDateTime": "2026-11-26T07:00:00Z", "appDisplayName": "Office 365", "ipAddress": "203.0.113.7",
             "location": {"city": "Milano", "countryOrRegion": "IT"}, "status": {"errorCode": 0}, "conditionalAccessStatus": "success"},
            {"userId": UID, "createdDateTime": "2026-11-26T06:00:00Z", "appDisplayName": "Azure Portal", "ipAddress": "198.51.100.9",
             "location": {"countryOrRegion": "RU"}, "status": {"errorCode": 50126, "failureReason": "Invalid password"},
             "conditionalAccessStatus": "notApplied", "riskLevelDuringSignIn": "high"}]
    c = ctx(fake_http, [token(ok), ("GET", f"{G}/auditLogs/signIns", ok(200, {"value": rows}))])
    [r] = entra.run(c, "user_signins", {"user": "Mario.Rossi@acme.com"})
    assert c.http.requests[1]["params"]["$filter"] == "userPrincipalName eq 'mario.rossi@acme.com'"
    assert r.fields == {"Sign-ins": "2", "Failed": "1"}
    assert "IP 198.51.100.9 (RU) · failed (Invalid password)" in r.text and "risk high" in r.text
    assert r.url.endswith(UID)


def test_risky_users_sorted(fake_http, ok):
    rows = [{"id": UID, "userPrincipalName": "a@acme.com", "riskLevel": "low", "riskState": "atRisk"},
            {"id": UID, "userPrincipalName": "b@acme.com", "riskLevel": "high", "riskState": "atRisk"}]
    c = ctx(fake_http, [token(ok), ("GET", f"{G}/identityProtection/riskyUsers", ok(200, {"value": rows}))])
    assert [r.id for r in entra.run(c, "risky_users", {})] == ["b@acme.com", "a@acme.com"]


def test_origins_and_patterns():
    cfg = {"tenant_id": TENANT}
    assert entra.origins(cfg) == ["https://login.microsoftonline.com", "https://graph.microsoft.com"]
    assert entra.read_posts(cfg) == [TOKEN_URL]
    pat = entra.operation("get_user").params["user"].pattern
    assert re.fullmatch(pat, "mario.rossi@acme.com") and re.fullmatch(pat, "Mario Rossi") and not re.fullmatch(pat, "x');drop")
