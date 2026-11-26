"""Microsoft Entra ID connector (read-only): a user (account state, MFA methods, risk, last
sign-in), the recent sign-ins of a user, the users at risk.

API: Microsoft Graph v1.0 with an Entra app registration (client credentials, application
permissions with admin consent): User.Read.All, AuditLog.Read.All (sign-ins and last sign-in,
Entra ID P1), UserAuthenticationMethod.Read.All (MFA methods), IdentityRiskyUser.Read.All
(risk, Entra ID P2). A permission or licence that is missing only leaves that part out.
Links open the user in the Entra admin center.
"""

import re
import time
from urllib.parse import quote

from app.connectors.contract import (
    IDENTITY,
    USER,
    Connector,
    ConnectorError,
    Context,
    Manifest,
    Operation,
    Param,
    Record,
    clip,
    status_error,
)

PRODUCT = "Entra ID"
LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com"
PORTAL = "https://entra.microsoft.com"
SCOPE = "https://graph.microsoft.com/.default"
TENANT = r"[0-9a-fA-F-]{36}|[A-Za-z0-9.-]{3,253}"
UPN = r"[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}"
# A UPN or e-mail, or the start of a display name (letters, digits, spaces, . ' -).
USER_ARG = UPN + r"|[\w][\w .'-]{1,99}"
USER_SELECT = ("id,displayName,userPrincipalName,mail,accountEnabled,jobTitle,department,officeLocation,companyName,"
               "createdDateTime,lastPasswordChangeDateTime,onPremisesSyncEnabled,userType,usageLocation")
METHODS = {"#microsoft.graph.microsoftAuthenticatorAuthenticationMethod": "Authenticator app",
           "#microsoft.graph.phoneAuthenticationMethod": "Phone", "#microsoft.graph.fido2AuthenticationMethod": "FIDO2 key",
           "#microsoft.graph.windowsHelloForBusinessAuthenticationMethod": "Windows Hello",
           "#microsoft.graph.softwareOathAuthenticationMethod": "OTP app", "#microsoft.graph.emailAuthenticationMethod": "E-mail",
           "#microsoft.graph.temporaryAccessPassAuthenticationMethod": "Temporary access pass",
           "#microsoft.graph.platformCredentialAuthenticationMethod": "Platform credential"}


def _odata(value: str) -> str:
    """A value inside OData single quotes."""
    return value.replace("'", "''")


class EntraId(Connector):
    manifest = Manifest(name="entraid", label=PRODUCT, version="1.0.0", type=IDENTITY, vendor="Microsoft",
                        description="Entra ID users: account state, MFA methods, risk, last sign-in; recent sign-ins of a user; users at risk.")
    config_schema = {
        "type": "object",
        "required": ["tenant_id", "client_id", "client_secret"],
        "properties": {
            "tenant_id": {"type": "string", "title": "Entra tenant ID", "maxLength": 253,
                          "description": "Directory (tenant) ID of the customer's Entra ID"},
            "client_id": {"type": "string", "title": "Application (client) ID", "maxLength": 64},
            "client_secret": {"type": "string", "title": "Client secret", "secret": True, "maxLength": 500},
        },
    }
    operations = (
        Operation("get_user", "User", "Details of a user by e-mail / UPN or name: enabled or blocked, MFA methods, risk, "
                  "last sign-in, password change, department.", USER,
                  {"user": Param("e-mail / UPN, or the start of the display name", pattern=USER_ARG, max_length=254)}),
        Operation("user_signins", "Recent sign-ins", "The last sign-ins of a user (e-mail / UPN): time, app, IP, country, "
                  "result, Conditional Access, risk.", USER,
                  {"user": Param("e-mail / UPN", pattern=UPN, max_length=254)}),
        Operation("risky_users", "Users at risk", "Users that Identity Protection currently marks at risk, highest risk first.",
                  USER, {}),
    )

    # --- Contract -------------------------------------------------------------------------

    def _token_url(self, config: dict) -> str:
        tenant = (config.get("tenant_id") or "").strip()
        if not re.fullmatch(TENANT, tenant):
            raise ConnectorError("Entra ID: invalid tenant ID", retryable=False, public=True)
        return f"{LOGIN}/{tenant}/oauth2/v2.0/token"

    def origins(self, config: dict) -> list[str]:
        return [LOGIN, GRAPH]

    def read_posts(self, config: dict) -> list[str]:
        return [self._token_url(config)]

    def test_connection(self, ctx: Context) -> str:
        self._get(ctx, "/v1.0/users", {"$top": "1", "$select": "id"})
        return "Connected: users readable"

    def run(self, ctx: Context, operation: str, args: dict) -> list[Record]:
        if operation == "get_user":
            return [self._user(ctx, u) for u in self._find(ctx, args["user"])[:2]]  # 4 requests each: stay under the cap
        if operation == "user_signins":
            return self._signins(ctx, args["user"])
        if operation == "risky_users":
            rows = self._get(ctx, "/v1.0/identityProtection/riskyUsers",
                             {"$filter": "riskState eq 'atRisk'", "$top": "50"}).get("value") or []
            order = {"high": 0, "medium": 1, "low": 2}
            rows = sorted((r for r in rows if isinstance(r, dict)), key=lambda r: order.get(str(r.get("riskLevel")), 3))
            return [Record(kind=USER, id=clip(r.get("userPrincipalName"), 254) or clip(r.get("id"), 64),
                           title=clip(r.get("userDisplayName"), 120), url=_user_url(r.get("id")),
                           fields={k: v for k, v in {"Risk level": clip(r.get("riskLevel"), 20), "Risk state": clip(r.get("riskState"), 30),
                                                     "Risk detail": clip(r.get("riskDetail"), 80),
                                                     "Risk updated": clip(r.get("riskLastUpdatedDateTime"), 40)}.items() if v})
                    for r in rows[:10]]
        raise ConnectorError(f"Unknown operation {operation}", retryable=False)

    # --- Requests --------------------------------------------------------------------------

    def _token(self, ctx: Context) -> str:
        st = ctx.state
        if st.get("token") and st.get("expires", 0) > time.time() + 60:
            return st["token"]
        if not ctx.config.get("client_id") or not ctx.secrets.get("client_secret"):
            raise ConnectorError("Entra ID: client ID or secret missing", retryable=False, public=True)
        r = ctx.http.request("POST", self._token_url(ctx.config), headers={"Accept": "application/json"},
                             data={"grant_type": "client_credentials", "client_id": ctx.config["client_id"],
                                   "client_secret": ctx.secrets["client_secret"], "scope": SCOPE})
        if r.status != 200:
            raise status_error(PRODUCT + " (sign-in)", r.status)
        body = r.json() or {}
        if not isinstance(body.get("access_token"), str):
            raise ConnectorError("Entra ID: no token in the answer", retryable=False)
        st["token"], st["expires"] = body["access_token"], time.time() + float(body.get("expires_in") or 3599)
        return st["token"]

    def _request(self, ctx: Context, path: str, params: dict, extra: dict | None = None):
        for attempt in (1, 2):
            r = ctx.http.request("GET", GRAPH + path, params=params,
                                 headers={"Accept": "application/json", "Authorization": f"Bearer {self._token(ctx)}", **(extra or {})})
            if r.status == 401 and attempt == 1:
                ctx.state.clear()
                continue
            return r
        return r

    def _get(self, ctx: Context, path: str, params: dict, extra: dict | None = None) -> dict:
        r = self._request(ctx, path, params, extra)
        if r.status != 200:
            raise status_error(PRODUCT, r.status)
        body = r.json()
        if not isinstance(body, dict):
            raise ConnectorError("Entra ID returned an unexpected answer")
        return body

    def _optional(self, ctx: Context, path: str, params: dict) -> dict | None:
        """A part that needs a permission or licence the customer may not have: None when refused."""
        r = self._request(ctx, path, params)
        if r.status in (400, 403, 404):
            return None
        if r.status != 200:
            raise status_error(PRODUCT, r.status)
        body = r.json()
        return body if isinstance(body, dict) else None

    def _find(self, ctx: Context, who: str) -> list[dict]:
        if re.fullmatch(UPN, who):
            r = self._request(ctx, f"/v1.0/users/{quote(who, safe='@')}", {"$select": USER_SELECT})
            if r.status == 200 and isinstance(r.json(), dict):
                return [r.json()]
            if r.status not in (400, 404):
                raise status_error(PRODUCT, r.status)
            # An e-mail that is not the UPN: look it up as mail or alias.
            flt = f"mail eq '{_odata(who)}' or proxyAddresses/any(p:p eq 'smtp:{_odata(who)}')"
            rows = self._get(ctx, "/v1.0/users", {"$filter": flt, "$select": USER_SELECT, "$count": "true", "$top": "3"},
                             {"ConsistencyLevel": "eventual"}).get("value") or []
        else:
            rows = self._get(ctx, "/v1.0/users", {"$filter": f"startswith(displayName,'{_odata(who)}')",
                                                  "$select": USER_SELECT, "$top": "3"}).get("value") or []
        return [u for u in rows if isinstance(u, dict)]

    # --- Records ---------------------------------------------------------------------------

    def _user(self, ctx: Context, u: dict) -> Record:
        uid = str(u.get("id") or "")
        fields = {"Account": "enabled" if u.get("accountEnabled") else "blocked (sign-in disabled)" if u.get("accountEnabled") is False else "",
                  "Name": clip(u.get("displayName"), 120), "E-mail": clip(u.get("mail"), 254),
                  "Job title": clip(u.get("jobTitle"), 120), "Department": clip(u.get("department"), 120),
                  "Office": clip(u.get("officeLocation"), 120), "Company": clip(u.get("companyName"), 120),
                  "Type": clip(u.get("userType"), 20), "Synced from on-premises AD": "yes" if u.get("onPremisesSyncEnabled") else "",
                  "Created": clip(u.get("createdDateTime"), 40), "Password changed": clip(u.get("lastPasswordChangeDateTime"), 40)}
        if re.fullmatch(r"[0-9a-fA-F-]{36}", uid):
            activity = self._optional(ctx, f"/v1.0/users/{uid}", {"$select": "signInActivity"})
            sia = (activity or {}).get("signInActivity") or {}
            fields["Last sign-in"] = clip(sia.get("lastSignInDateTime"), 40)
            fields["Last successful sign-in"] = clip(sia.get("lastSuccessfulSignInDateTime"), 40)
            methods = self._optional(ctx, f"/v1.0/users/{uid}/authentication/methods", {})
            if methods is not None:
                kinds = sorted({METHODS.get(m.get("@odata.type"), "") for m in methods.get("value") or [] if isinstance(m, dict)} - {""})
                fields["MFA methods"] = ", ".join(kinds) or "none registered (password only)"
            risk = self._optional(ctx, f"/v1.0/identityProtection/riskyUsers/{uid}", {})
            if risk:
                fields["Risk"] = clip(" · ".join(str(x) for x in (risk.get("riskLevel"), risk.get("riskState")) if x), 60)
        return Record(kind=USER, id=clip(u.get("userPrincipalName"), 254) or uid, title=clip(u.get("displayName"), 120),
                      url=_user_url(uid), fields={k: v for k, v in fields.items() if v})

    def _signins(self, ctx: Context, upn: str) -> list[Record]:
        body = self._get(ctx, "/v1.0/auditLogs/signIns", {"$filter": f"userPrincipalName eq '{_odata(upn.lower())}'", "$top": "10"})
        rows = [s for s in body.get("value") or [] if isinstance(s, dict)]
        if not rows:
            return []
        lines, uid = [], ""
        for s in rows:
            uid = uid or str(s.get("userId") or "")
            st = s.get("status") if isinstance(s.get("status"), dict) else {}
            loc = s.get("location") if isinstance(s.get("location"), dict) else {}
            dev = s.get("deviceDetail") if isinstance(s.get("deviceDetail"), dict) else {}
            ok = st.get("errorCode") in (0, None)
            result = "success" if ok else f"failed ({clip(st.get('failureReason'), 120)})"
            where = ", ".join(x for x in (loc.get("city"), loc.get("countryOrRegion")) if x)
            lines.append(f"- {clip(s.get('createdDateTime'), 25)} · {clip(s.get('appDisplayName'), 60)} · IP {clip(s.get('ipAddress'), 45)}"
                         + (f" ({where})" if where else "") + f" · {result}"
                         + f" · Conditional Access {clip(s.get('conditionalAccessStatus'), 20)}"
                         + (f" · risk {s['riskLevelDuringSignIn']}" if s.get("riskLevelDuringSignIn") not in (None, "none", "hidden") else "")
                         + (f" · {clip(dev.get('operatingSystem'), 30)} {clip(dev.get('browser'), 40)}".rstrip() if dev else ""))
        failed = sum(1 for s in rows if (s.get("status") or {}).get("errorCode") not in (0, None))
        return [Record(kind=USER, id=upn, title=f"Last {len(rows)} sign-ins", url=_user_url(uid),
                       fields={"Sign-ins": str(len(rows)), "Failed": str(failed)}, text="\n".join(lines),
                       links={"Sign-in logs": f"{PORTAL}/#view/Microsoft_AAD_IAM/SignInEventsV3Blade"})]


def _user_url(user_id) -> str | None:
    uid = str(user_id or "")
    return f"{PORTAL}/#view/Microsoft_AAD_UsersAndTenants/UserProfileMenuBlade/~/overview/userId/{uid}" \
        if re.fullmatch(r"[0-9a-fA-F-]{36}", uid) else None


connector = EntraId()
