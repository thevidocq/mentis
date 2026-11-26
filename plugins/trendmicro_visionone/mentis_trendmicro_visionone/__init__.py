"""Trend Micro Vision One connector (read-only): endpoints, Workbench alerts of an endpoint,
alert by id, open alerts.

API: Vision One API v3.0 with an API key (Administration > API Keys) whose role can view
Endpoint Inventory and Workbench. Regional API hosts; links open the alert in Workbench.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlsplit

from app.connectors.contract import (
    ALERT,
    DEVICE,
    EDR,
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

PRODUCT = "Trend Vision One"
APIS = {"us": "https://api.xdr.trendmicro.com", "eu": "https://api.eu.xdr.trendmicro.com",
        "jp": "https://api.xdr.trendmicro.co.jp", "sg": "https://api.sg.xdr.trendmicro.com",
        "au": "https://api.au.xdr.trendmicro.com", "in": "https://api.in.xdr.trendmicro.com",
        "mea": "https://api.mea.xdr.trendmicro.com"}
HOST = r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}"
ALERT_ID = r"WB-\d{1,10}-\d{8}-\d{3,10}"
LEVELS = ["low", "medium", "high", "critical"]


def _trend_link(url) -> str | None:
    """Workbench links from the API, only when they point to a Trend Micro host."""
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    host = (urlsplit(url).hostname or "").lower()
    return url if host.endswith((".trendmicro.com", ".trendmicro.co.jp")) else None


class VisionOne(Connector):
    manifest = Manifest(name="trendmicro_visionone", label=PRODUCT, version="1.0.0", type=EDR, vendor="Trend Micro",
                        description="Vision One endpoints and Workbench alerts: endpoint details, alerts of an endpoint, alert by id, open alerts.")
    config_schema = {
        "type": "object",
        "required": ["region", "api_key"],
        "properties": {
            "region": {"type": "string", "title": "Region", "enum": list(APIS), "default": "eu",
                       "enumLabels": ["United States", "Europe", "Japan", "Singapore", "Australia", "India", "Middle East and Africa"]},
            "api_key": {"type": "string", "title": "API key", "secret": True, "maxLength": 4000},
        },
    }
    operations = (
        Operation("get_endpoint", "Endpoint", "Details of an endpoint by name: OS, IPs, agent and sensor state, last connection.",
                  DEVICE, {"host": Param("endpoint (host) name", pattern=HOST, max_length=253)}),
        Operation("endpoint_alerts", "Alerts of an endpoint", "Workbench alerts of the last 30 days that involve an endpoint, newest first.",
                  ALERT, {"host": Param("endpoint (host) name", pattern=HOST, max_length=253)}),
        Operation("get_alert", "Alert by id", "Read one Workbench alert by its id (WB-...).", ALERT,
                  {"alert_id": Param("Workbench alert id, e.g. WB-14-20240709-00003", pattern=ALERT_ID, max_length=40)},
                  match={"alert_id": r"\b" + ALERT_ID + r"\b"}),
        Operation("open_alerts", "Open alerts", "Newest Workbench alerts of the last 7 days that are not closed, optionally from a minimum severity.",
                  ALERT, {"min_severity": Param("low, medium, high or critical", required=False, pattern=r"(?i)low|medium|high|critical")}),
    )

    # --- Contract -------------------------------------------------------------------------

    def _api(self, config: dict) -> str:
        api = APIS.get(config.get("region") or "eu")
        if api is None:
            raise ConnectorError("Vision One: unknown region", retryable=False, public=True)
        return api

    def origins(self, config: dict) -> list[str]:
        return [self._api(config)]

    def test_connection(self, ctx: Context) -> str:
        self._get(ctx, "/v3.0/endpointSecurity/endpoints", {"top": "10"})
        return "Connected: endpoints readable"

    def run(self, ctx: Context, operation: str, args: dict) -> list[Record]:
        if operation == "get_endpoint":
            name = args["host"].replace("'", "")
            items = self._get(ctx, "/v3.0/endpointSecurity/endpoints", {"top": "10"},
                              {"TMV1-Filter": f"endpointName eq '{name}'"}).get("items") or []
            return [self._endpoint(e) for e in items[:5] if isinstance(e, dict)]
        if operation == "endpoint_alerts":
            host = args["host"].lower()
            rows = [a for a in self._alerts(ctx, days=30) if host in _hosts(a)]
            return [self._alert(a) for a in rows[:5]]
        if operation == "get_alert":
            try:
                a = self._get(ctx, f"/v3.0/workbench/alerts/{quote(args['alert_id'], safe='')}", {})
            except ConnectorError as e:
                if "404" in str(e):
                    return []
                raise
            return [self._alert(a)]
        if operation == "open_alerts":
            level = (args.get("min_severity") or "low").lower()
            floor = LEVELS.index(level) if level in LEVELS else 0
            rows = [a for a in self._alerts(ctx, days=7) if str(a.get("status") or "").lower() != "closed"
                    and (str(a.get("severity") or "").lower() not in LEVELS or LEVELS.index(str(a["severity"]).lower()) >= floor)]
            return [self._alert(a) for a in rows[:5]]
        raise ConnectorError(f"Unknown operation {operation}", retryable=False)

    # --- Requests --------------------------------------------------------------------------

    def _get(self, ctx: Context, path: str, params: dict, extra: dict | None = None) -> dict:
        if not ctx.secrets.get("api_key"):
            raise ConnectorError("Vision One: API key missing", retryable=False, public=True)
        headers = {"Accept": "application/json", "Authorization": f"Bearer {ctx.secrets['api_key']}", **(extra or {})}
        r = ctx.http.request("GET", self._api(ctx.config) + path, params=params, headers=headers)
        if r.status != 200:
            raise status_error(PRODUCT, r.status)
        body = r.json()
        if not isinstance(body, dict):
            raise ConnectorError("Vision One returned an unexpected answer")
        return body

    def _alerts(self, ctx: Context, days: int) -> list[dict]:
        now = datetime.now(UTC)
        params = {"startDateTime": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "endDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "dateTimeTarget": "createdDateTime",
                  "orderBy": "createdDateTime desc"}
        items = self._get(ctx, "/v3.0/workbench/alerts", params).get("items") or []
        return [a for a in items if isinstance(a, dict)]

    # --- Records ---------------------------------------------------------------------------

    def _endpoint(self, e: dict) -> Record:
        def v(x):  # Endpoint Inventory values are plain or {"value": ...}
            return x.get("value") if isinstance(x, dict) and "value" in x else x

        os_ = e.get("os") if isinstance(e.get("os"), dict) else {}
        epp = e.get("eppAgent") if isinstance(e.get("eppAgent"), dict) else {}
        edr = e.get("edrSensor") if isinstance(e.get("edrSensor"), dict) else {}
        ips = v(e.get("ipAddresses")) or v(e.get("ip")) or []
        fields = {"OS": clip(" ".join(x for x in (os_.get("name"), os_.get("version")) if x) or v(e.get("osName")), 120),
                  "Type": clip(e.get("type"), 40), "IP addresses": clip(", ".join(ips) if isinstance(ips, list) else ips, 200),
                  "Last used IP": clip(e.get("lastUsedIp"), 60),
                  "Protection agent": clip(" · ".join(str(x) for x in (epp.get("status"), epp.get("lastConnectedDateTime")) if x), 120),
                  "Sensor (EDR)": clip(" · ".join(str(x) for x in (edr.get("status"), edr.get("connectivity"),
                                                                   edr.get("lastConnectedDateTime")) if x), 160),
                  "Isolation": clip(e.get("isolationStatus") or edr.get("isolationStatus"), 40),
                  "Agent GUID": clip(e.get("agentGuid"), 64)}
        return Record(kind=DEVICE, id=clip(v(e.get("endpointName")), 253) or clip(e.get("agentGuid"), 64),
                      title=clip(e.get("displayName") or fields["OS"], 120), fields={k: x for k, x in fields.items() if x},
                      updated=clip(edr.get("lastConnectedDateTime") or epp.get("lastConnectedDateTime"), 40) or None)

    def _alert(self, a: dict) -> Record:
        indicators = [f"- {clip(i.get('type'), 30)}: {clip(i.get('value'), 200)}"
                      for i in (a.get("indicators") or [])[:15] if isinstance(i, dict) and i.get("value") not in (None, "")]
        rules = ", ".join(clip(r.get("name"), 80) for r in (a.get("matchedRules") or [])[:5] if isinstance(r, dict))
        fields = {"Severity": clip(a.get("severity"), 20), "Score": clip(a.get("score"), 10), "Status": clip(a.get("status"), 30),
                  "Investigation": clip(a.get("investigationResult") or a.get("investigationStatus"), 60),
                  "Endpoints": clip(", ".join(sorted(_hosts(a, original=True))), 300), "Matched rules": clip(rules, 300),
                  "Created": clip(a.get("createdDateTime"), 40)}
        text = "\n".join(x for x in (clip(a.get("description"), 1200),
                                     ("Indicators:\n" + "\n".join(indicators)) if indicators else "") if x)
        alert_id = str(a.get("id") or "")
        return Record(kind=ALERT, id=alert_id, title=clip(a.get("model") or a.get("name"), 200),
                      url=_trend_link(a.get("workbenchLink")), fields={k: x for k, x in fields.items() if x},
                      text=text or None, updated=clip(a.get("updatedDateTime"), 40) or None)


def _hosts(a: dict, original: bool = False) -> set[str]:
    """Host names in an alert's impact scope."""
    out = set()
    scope = a.get("impactScope") if isinstance(a.get("impactScope"), dict) else {}
    for e in scope.get("entities") or []:
        if not isinstance(e, dict) or str(e.get("entityType", "")).lower() not in ("host", "endpoint"):
            continue
        value = e.get("entityValue")
        name = value.get("name") if isinstance(value, dict) else value
        if isinstance(name, str) and name:
            out.add(name if original else name.lower())
            if not original and "." in name:
                out.add(name.lower().split(".")[0])
    return out


connector = VisionOne()
