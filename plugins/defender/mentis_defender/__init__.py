"""Microsoft Defender for Endpoint connector (read-only): devices, alerts of a device, alert by id,
open alerts, IP statistics.

API: Defender for Endpoint API with an Entra ID app (client credentials, application permissions
Machine.Read.All, Alert.Read.All, Ip.Read.All). Token from login.microsoftonline.com (a POST that
only reads), data from the regional API host. Links open the Microsoft Defender portal.
"""

import re
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from app.connectors.contract import (
    ALERT,
    DEVICE,
    EDR,
    INDICATOR,
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

PRODUCT = "Microsoft Defender"
LOGIN = "https://login.microsoftonline.com"
PORTAL = "https://security.microsoft.com"
SCOPE = "https://api.securitycenter.microsoft.com/.default"
APIS = {"global": "https://api.securitycenter.microsoft.com", "us": "https://api-us.securitycenter.microsoft.com",
        "eu": "https://api-eu.securitycenter.microsoft.com", "uk": "https://api-uk.securitycenter.microsoft.com",
        "au": "https://api-au.securitycenter.microsoft.com"}
HOST = r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}"
ALERT_ID = r"[A-Za-z0-9][A-Za-z0-9_-]{9,99}"
IPV4 = r"(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)"
IP = IPV4 + r"|[0-9A-Fa-f:]{2,39}"
TENANT = r"[0-9a-fA-F-]{36}|[A-Za-z0-9.-]{3,253}"
LEVELS = ["Informational", "Low", "Medium", "High"]


class Defender(Connector):
    manifest = Manifest(name="defender", label=PRODUCT, version="1.0.0", type=EDR, vendor="Microsoft",
                        description="Defender for Endpoint devices, alerts and IP statistics, with links to the Defender portal.")
    config_schema = {
        "type": "object",
        "required": ["tenant_id", "client_id", "client_secret", "region"],
        "properties": {
            "tenant_id": {"type": "string", "title": "Entra tenant ID", "maxLength": 253,
                          "description": "Directory (tenant) ID of the customer's Entra ID"},
            "client_id": {"type": "string", "title": "Application (client) ID", "maxLength": 64},
            "client_secret": {"type": "string", "title": "Client secret", "secret": True, "maxLength": 500},
            "region": {"type": "string", "title": "API region", "enum": list(APIS), "default": "global",
                       "enumLabels": ["Global", "United States", "Europe", "United Kingdom", "Australia"]},
        },
    }
    operations = (
        Operation("get_device", "Device", "Details of a device by host name: OS, health, risk, exposure, last seen, IPs, tags.",
                  DEVICE, {"host": Param("host name (the start of the DNS name is enough)", pattern=HOST, max_length=253)}),
        Operation("device_alerts", "Alerts of a device", "Most recent alerts of a device that are not resolved, newest first.",
                  ALERT, {"host": Param("host name", pattern=HOST, max_length=253)}),
        Operation("get_alert", "Alert by id", "Read one alert by its id, with its evidence (files, IPs, users).", ALERT,
                  {"alert_id": Param("alert id, e.g. da637292082891366787_322230012", pattern=ALERT_ID, max_length=100)},
                  match={"alert_id": r"\b(?:da|ed|fa|wd|ta|dl)\d{15,22}_-?\d{4,12}\b"}),
        Operation("open_alerts", "Open alerts", "Newest alerts of the last 7 days that are not resolved, optionally from a minimum severity.",
                  ALERT, {"min_severity": Param("low, medium or high", required=False, pattern=r"(?i)informational|low|medium|high")}),
        Operation("ip_info", "IP address", "What Defender saw of an IP address in the last 30 days: devices that talked to it, first and last seen.",
                  INDICATOR, {"ip": Param("IP address", pattern=IP, max_length=39)}),
    )

    # --- Contract -------------------------------------------------------------------------

    def _api(self, config: dict) -> str:
        api = APIS.get(config.get("region") or "global")
        if api is None:
            raise ConnectorError("Defender: unknown region", retryable=False, public=True)
        return api

    def _token_url(self, config: dict) -> str:
        tenant = (config.get("tenant_id") or "").strip()
        if not re.fullmatch(TENANT, tenant):
            raise ConnectorError("Defender: invalid tenant ID", retryable=False, public=True)
        return f"{LOGIN}/{tenant}/oauth2/v2.0/token"

    def origins(self, config: dict) -> list[str]:
        return [LOGIN, self._api(config)]

    def read_posts(self, config: dict) -> list[str]:
        return [self._token_url(config)]

    def test_connection(self, ctx: Context) -> str:
        self._get(ctx, "/api/machines", {"$top": "1"})
        return "Connected: devices readable"

    def run(self, ctx: Context, operation: str, args: dict) -> list[Record]:
        if operation == "get_device":
            return [self._device(m) for m in self._machines(ctx, args["host"])]
        if operation == "device_alerts":
            machines = self._machines(ctx, args["host"])
            if not machines:
                return []
            rows = self._get(ctx, f"/api/machines/{quote(str(machines[0].get('id', '')), safe='')}/alerts", {}).get("value") or []
            rows = [a for a in rows if isinstance(a, dict) and a.get("status") != "Resolved"]
            rows.sort(key=lambda a: str(a.get("alertCreationTime") or ""), reverse=True)
            return [self._alert(a) for a in rows[:5]]
        if operation == "get_alert":
            try:
                a = self._get(ctx, f"/api/alerts/{quote(args['alert_id'], safe='')}", {"$expand": "evidence"})
            except ConnectorError as e:
                if "404" in str(e):
                    return []
                raise
            return [self._alert(a)]
        if operation == "open_alerts":
            since = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows = self._get(ctx, "/api/alerts", {"$filter": f"alertCreationTime ge {since}", "$top": "100"}).get("value") or []
            level = (args.get("min_severity") or "").capitalize()
            floor = LEVELS.index(level) if level in LEVELS else 0
            rows = [a for a in rows if isinstance(a, dict) and a.get("status") != "Resolved"
                    and (a.get("severity") not in LEVELS or LEVELS.index(a["severity"]) >= floor)]
            rows.sort(key=lambda a: str(a.get("alertCreationTime") or ""), reverse=True)
            return [self._alert(a) for a in rows[:5]]
        if operation == "ip_info":
            ip = args["ip"]
            stats = self._get(ctx, f"/api/ips/{quote(ip, safe='')}/stats", {"lookBackHours": "720"})
            fields = {"Devices that communicated with it": clip(stats.get("orgPrevalence"), 20),
                      "First seen": clip(stats.get("orgFirstSeen"), 40), "Last seen": clip(stats.get("orgLastSeen"), 40)}
            return [Record(kind=INDICATOR, id=ip, title="IP address, last 30 days", url=_ip_url(ip),
                           fields={k: v for k, v in fields.items() if v})]
        raise ConnectorError(f"Unknown operation {operation}", retryable=False)

    # --- Requests --------------------------------------------------------------------------

    def _token(self, ctx: Context) -> str:
        st = ctx.state
        if st.get("token") and st.get("expires", 0) > time.time() + 60:
            return st["token"]
        if not ctx.config.get("client_id") or not ctx.secrets.get("client_secret"):
            raise ConnectorError("Defender: client ID or secret missing", retryable=False, public=True)
        r = ctx.http.request("POST", self._token_url(ctx.config), headers={"Accept": "application/json"},
                             data={"grant_type": "client_credentials", "client_id": ctx.config["client_id"],
                                   "client_secret": ctx.secrets["client_secret"], "scope": SCOPE})
        if r.status != 200:
            raise status_error(PRODUCT + " (sign-in)", r.status)
        body = r.json() or {}
        if not isinstance(body.get("access_token"), str):
            raise ConnectorError("Defender: no token in the answer", retryable=False)
        st["token"], st["expires"] = body["access_token"], time.time() + float(body.get("expires_in") or 3599)
        return st["token"]

    def _get(self, ctx: Context, path: str, params: dict) -> dict:
        url = self._api(ctx.config) + path
        for attempt in (1, 2):
            r = ctx.http.request("GET", url, params=params,
                                 headers={"Accept": "application/json", "Authorization": f"Bearer {self._token(ctx)}"})
            if r.status == 401 and attempt == 1:
                ctx.state.clear()
                continue
            break
        if r.status != 200:
            raise status_error(PRODUCT, r.status)
        body = r.json()
        if not isinstance(body, dict):
            raise ConnectorError("Defender returned an unexpected answer")
        return body

    def _machines(self, ctx: Context, host: str) -> list[dict]:
        name = host.lower().replace("'", "")
        rows = self._get(ctx, "/api/machines", {"$filter": f"startswith(computerDnsName,'{name}')", "$top": "5"}).get("value") or []
        rows = [m for m in rows if isinstance(m, dict)]
        # The exact name (or its FQDN) first.
        rows.sort(key=lambda m: str(m.get("computerDnsName") or "").lower().split(".")[0] != name.split(".")[0])
        return rows

    # --- Records ---------------------------------------------------------------------------

    def _device(self, m: dict) -> Record:
        fields = {"OS": clip(" ".join(x for x in (m.get("osPlatform"), m.get("version") or m.get("osVersion")) if x), 120),
                  "Health": clip(m.get("healthStatus"), 40), "Risk": clip(m.get("riskScore"), 40),
                  "Exposure": clip(m.get("exposureLevel"), 40), "Last seen": clip(m.get("lastSeen"), 40),
                  "First seen": clip(m.get("firstSeen"), 40), "Last IP": clip(m.get("lastIpAddress"), 60),
                  "External IP": clip(m.get("lastExternalIpAddress"), 60), "Onboarding": clip(m.get("onboardingStatus"), 40),
                  "Tags": clip(", ".join(m.get("machineTags") or []), 200), "Device id": clip(m.get("id"), 64)}
        links = {f"IP {ip}": _ip_url(ip) for ip in (m.get("lastIpAddress"), m.get("lastExternalIpAddress")) if _ip_url(ip)}
        return Record(kind=DEVICE, id=clip(m.get("computerDnsName"), 253) or clip(m.get("id"), 64), title=clip(m.get("osPlatform"), 80),
                      url=_device_url(m.get("id")), fields={k: v for k, v in fields.items() if v}, links=links,
                      updated=clip(m.get("lastSeen"), 40) or None)

    def _alert(self, a: dict) -> Record:
        techniques = ", ".join(a.get("mitreTechniques") or [])
        fields = {"Severity": clip(a.get("severity"), 40), "Status": clip(a.get("status"), 40),
                  "Device": clip(a.get("computerDnsName"), 253), "Category": clip(a.get("category"), 80),
                  "Techniques": clip(techniques, 200), "Classification": clip(a.get("classification"), 60),
                  "Determination": clip(a.get("determination"), 60), "Assigned to": clip(a.get("assignedTo"), 120),
                  "Created": clip(a.get("alertCreationTime"), 40), "Incident": clip(a.get("incidentId"), 40)}
        links = {}
        if _device_url(a.get("machineId")):
            links[f"Device {a.get('computerDnsName') or a.get('machineId')}"] = _device_url(a.get("machineId"))
        if re.fullmatch(r"\d{1,20}", str(a.get("incidentId") or "")):
            links[f"Incident {a['incidentId']}"] = f"{PORTAL}/incidents/{a['incidentId']}"
        evidence = []
        for e in (a.get("evidence") or [])[:15]:
            if not isinstance(e, dict):
                continue
            what = e.get("fileName") or e.get("ipAddress") or e.get("url") or e.get("accountName") or e.get("processCommandLine")
            if what:
                evidence.append(f"- {clip(e.get('entityType'), 30)}: {clip(what, 200)}"
                                + (f" (SHA-256 {e['sha256']})" if isinstance(e.get("sha256"), str) else ""))
            if e.get("ipAddress") and _ip_url(e["ipAddress"]) and len(links) < 5:
                links[f"IP {e['ipAddress']}"] = _ip_url(e["ipAddress"])
        text = "\n".join(x for x in (clip(a.get("description"), 1200), ("Evidence:\n" + "\n".join(evidence)) if evidence else "") if x)
        alert_id = str(a.get("id") or "")
        return Record(kind=ALERT, id=alert_id, title=clip(a.get("title"), 200),
                      url=f"{PORTAL}/alerts/{quote(alert_id, safe='')}" if re.fullmatch(ALERT_ID, alert_id) else None,
                      fields={k: v for k, v in fields.items() if v}, text=text or None, links=links,
                      updated=clip(a.get("lastUpdateTime"), 40) or None)


def _device_url(machine_id) -> str | None:
    return f"{PORTAL}/machines/{machine_id}/overview" if re.fullmatch(r"[0-9a-f]{40}", str(machine_id or "")) else None


def _ip_url(ip) -> str | None:
    return f"{PORTAL}/ip/{ip}/overview" if isinstance(ip, str) and re.fullmatch(IP, ip) else None


connector = Defender()
