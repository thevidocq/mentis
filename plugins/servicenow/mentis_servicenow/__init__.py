"""ServiceNow connector (read-only): tickets by number, search, open tickets of a host.

API: Table API (`/api/now/table/<table>`), display values on, so states, priorities and
references read as in the ServiceNow UI. Authentication: basic (user and password), OAuth client
credentials (`/oauth_token.do`) or API key (`x-sn-apikey`, Washington DC and later).
Permissions: a user with read access (e.g. `itil` or a custom read-only role) on the tables used.
"""

import base64
import re
import time
from urllib.parse import quote

from app.connectors.contract import (
    TICKET,
    TICKETING,
    Connector,
    ConnectorError,
    Context,
    Manifest,
    Operation,
    Param,
    Record,
    base_url,
    clip,
    origin_of,
    status_error,
)

PRODUCT = "ServiceNow"
NUMBER = r"(?:INC|SIR|PRB|CHG|RITM|SCTASK|TASK)\d{5,10}"
# Number prefix -> table. Unknown prefixes are looked up in the configured table.
PREFIX_TABLE = {"INC": "incident", "SIR": "sn_si_incident", "PRB": "problem", "CHG": "change_request",
                "RITM": "sc_req_item", "SCTASK": "sc_task", "TASK": "task"}
TABLES = ["incident", "sn_si_incident", "problem", "change_request", "sc_req_item", "sc_task"]
BASE_FIELDS = ["sys_id", "number", "short_description", "description", "state", "priority", "impact", "urgency",
               "category", "subcategory", "assignment_group", "assigned_to", "caller_id", "cmdb_ci", "opened_at",
               "sys_updated_on", "resolved_at", "close_code", "close_notes", "comments_and_work_notes"]
LABELS = {"state": "State", "priority": "Priority", "impact": "Impact", "urgency": "Urgency", "category": "Category",
          "subcategory": "Subcategory", "assignment_group": "Assignment group", "assigned_to": "Assigned to",
          "caller_id": "Caller", "cmdb_ci": "Configuration item", "opened_at": "Opened", "resolved_at": "Resolved",
          "close_code": "Close code", "close_notes": "Close notes"}
HOST = r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}"


def _clean_query(text: str) -> str:
    """Search words for an encoded query: no operators (^, =), no line breaks."""
    return re.sub(r"[\^=\r\n]", " ", text).strip()[:100]


class ServiceNow(Connector):
    manifest = Manifest(name="servicenow", label=PRODUCT, version="1.0.0", type=TICKETING, vendor="ServiceNow",
                        description="Incidents, security incidents, problems, changes and requests: read by number, search, open tickets of a host.")
    config_schema = {
        "type": "object",
        "required": ["instance_url"],
        "properties": {
            "instance_url": {"type": "string", "format": "uri", "title": "Instance URL", "maxLength": 300,
                             "description": "e.g. https://acme.service-now.com"},
            "auth": {"type": "string", "title": "Authentication", "enum": ["basic", "oauth", "api_key"], "default": "basic",
                     "enumLabels": ["User and password", "OAuth client credentials", "API key"]},
            "username": {"identity": True, "type": "string", "title": "User", "maxLength": 200, "showIf": {"auth": "basic"}},
            "password": {"type": "string", "title": "Password", "secret": True, "maxLength": 500, "showIf": {"auth": "basic"}},
            "client_id": {"identity": True, "type": "string", "title": "OAuth client ID", "maxLength": 200, "showIf": {"auth": "oauth"}},
            "client_secret": {"type": "string", "title": "OAuth client secret", "secret": True, "maxLength": 500, "showIf": {"auth": "oauth"}},
            "api_key": {"type": "string", "title": "API key", "secret": True, "maxLength": 500, "showIf": {"auth": "api_key"}},
            "table": {"type": "string", "title": "Table for searches", "enum": TABLES, "default": "incident",
                      "description": "sn_si_incident for Security Incident Response"},
            "extra_fields": {"type": "string", "title": "Extra fields", "maxLength": 500, "default": "",
                             "description": "Field mapping: more fields to read, comma separated (e.g. u_customer_ref, business_service)"},
        },
    }
    operations = (
        Operation("get_ticket", "Ticket by number", "Read one ticket by its number (INC, SIR, PRB, CHG, RITM, SCTASK).",
                  TICKET, {"number": Param("ticket number, e.g. INC0012345", pattern=r"(?i)" + NUMBER)},
                  match={"number": r"\b" + NUMBER + r"\b"}),
        Operation("search_tickets", "Search tickets", "Search tickets by words in the short description or description, newest first.",
                  TICKET, {"query": Param("search words", max_length=100, identifier=False),
                           "scope": Param("open (default) or all", required=False, pattern=r"(?i)open|all")}),
        Operation("tickets_for_host", "Open tickets of a host", "Open tickets about a host (configuration item name).",
                  TICKET, {"host": Param("host name", pattern=HOST, max_length=253)}),
    )

    # --- Contract -------------------------------------------------------------------------

    def origins(self, config: dict) -> list[str]:
        return [origin_of(config.get("instance_url", ""))]

    def read_posts(self, config: dict) -> list[str]:
        return [base_url(config.get("instance_url", "")) + "/oauth_token.do"]

    def test_connection(self, ctx: Context) -> str:
        table = ctx.config.get("table") or "incident"
        self._get(ctx, f"/api/now/table/{table}", {"sysparm_limit": "1", "sysparm_fields": "sys_id"})
        return f"Connected: {table} readable"

    def run(self, ctx: Context, operation: str, args: dict) -> list[Record]:
        if operation == "get_ticket":
            number = args["number"].upper()
            prefix = re.match(r"[A-Z]+", number).group(0)
            table = PREFIX_TABLE.get(prefix, ctx.config.get("table") or "incident")
            return self._query(ctx, table, f"number={number}", 1)
        if operation == "search_tickets":
            words = _clean_query(args["query"])
            if not words:
                return []
            q = f"short_descriptionLIKE{words}^ORdescriptionLIKE{words}"
            if (args.get("scope") or "open").lower() == "open":
                q = "active=true^" + q
            return self._query(ctx, ctx.config.get("table") or "incident", q + "^ORDERBYDESCsys_updated_on", 5)
        if operation == "tickets_for_host":
            host = args["host"]
            return self._query(ctx, ctx.config.get("table") or "incident",
                               f"active=true^cmdb_ci.name={host}^ORcmdb_ci.nameSTARTSWITH{host}.^ORDERBYDESCsys_updated_on", 5)
        raise ConnectorError(f"Unknown operation {operation}", retryable=False)

    # --- Requests --------------------------------------------------------------------------

    def _auth(self, ctx: Context) -> dict:
        cfg, sec = ctx.config, ctx.secrets
        mode = cfg.get("auth") or "basic"
        if mode == "api_key":
            if not sec.get("api_key"):
                raise ConnectorError("ServiceNow: API key missing", retryable=False, public=True)
            return {"x-sn-apikey": sec["api_key"]}
        if mode == "oauth":
            return {"Authorization": f"Bearer {self._token(ctx)}"}
        if not cfg.get("username") or not sec.get("password"):
            raise ConnectorError("ServiceNow: user or password missing", retryable=False, public=True)
        raw = f"{cfg['username']}:{sec['password']}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}

    def _token(self, ctx: Context) -> str:
        st = ctx.state
        if st.get("token") and st.get("expires", 0) > time.time() + 30:
            return st["token"]
        if not ctx.config.get("client_id") or not ctx.secrets.get("client_secret"):
            raise ConnectorError("ServiceNow: OAuth client ID or secret missing", retryable=False, public=True)
        r = ctx.http.request("POST", base_url(ctx.config["instance_url"]) + "/oauth_token.do",
                             data={"grant_type": "client_credentials", "client_id": ctx.config["client_id"],
                                   "client_secret": ctx.secrets["client_secret"]},
                             headers={"Accept": "application/json"})
        if r.status != 200:
            raise status_error(PRODUCT + " (OAuth)", r.status)
        data = r.json() or {}
        if not isinstance(data.get("access_token"), str):
            raise ConnectorError("ServiceNow (OAuth): no token in the answer", retryable=False)
        st["token"], st["expires"] = data["access_token"], time.time() + float(data.get("expires_in") or 1800)
        return st["token"]

    def _get(self, ctx: Context, path: str, params: dict) -> list[dict]:
        headers = {"Accept": "application/json", **self._auth(ctx)}
        r = ctx.http.request("GET", base_url(ctx.config["instance_url"]) + path, params=params, headers=headers)
        if r.status == 401 and (ctx.config.get("auth") == "oauth"):
            ctx.state.clear()  # token revoked or expired early: one new token
            headers = {"Accept": "application/json", **self._auth(ctx)}
            r = ctx.http.request("GET", base_url(ctx.config["instance_url"]) + path, params=params, headers=headers)
        if r.status != 200:
            raise status_error(PRODUCT, r.status)
        result = (r.json() or {}).get("result")
        if not isinstance(result, list):
            raise ConnectorError("ServiceNow returned an unexpected answer")
        return [x for x in result if isinstance(x, dict)]

    def _fields(self, ctx: Context) -> list[str]:
        extra = [f.strip() for f in (ctx.config.get("extra_fields") or "").split(",")]
        extra = [f for f in extra if re.fullmatch(r"[A-Za-z0-9_.]{1,80}", f)]
        return list(dict.fromkeys(BASE_FIELDS + extra))

    def _query(self, ctx: Context, table: str, query: str, limit: int) -> list[Record]:
        rows = self._get(ctx, f"/api/now/table/{table}", {
            "sysparm_query": query, "sysparm_limit": str(limit), "sysparm_display_value": "true",
            "sysparm_exclude_reference_link": "true", "sysparm_fields": ",".join(self._fields(ctx))})
        return [self._record(ctx, table, row) for row in rows]

    def _record(self, ctx: Context, table: str, row: dict) -> Record:
        def val(key):
            v = row.get(key)
            if isinstance(v, dict):  # display_value=all style
                v = v.get("display_value") or v.get("value")
            return clip(v, 300)

        fields = {LABELS[k]: val(k) for k in LABELS if k != "close_notes" and val(k)}
        for k in self._fields(ctx):
            if k not in BASE_FIELDS and val(k):
                fields[k] = val(k)
        text = []
        if val("description"):
            text.append("Description: " + clip(row.get("description"), 1500))
        if val("close_notes"):
            text.append("Close notes: " + clip(row.get("close_notes"), 600))
        if val("comments_and_work_notes"):
            text.append("Recent notes: " + str(row.get("comments_and_work_notes"))[:1200])
        sys_id = val("sys_id")
        url = (f"{base_url(ctx.config['instance_url'])}/{table}.do?sys_id={quote(sys_id)}"
               if re.fullmatch(r"[0-9a-f]{32}", sys_id or "") else None)
        return Record(kind=TICKET, id=val("number") or sys_id, title=val("short_description"), url=url,
                      fields=fields, text="\n".join(text) or None, updated=val("sys_updated_on") or None)


connector = ServiceNow()
