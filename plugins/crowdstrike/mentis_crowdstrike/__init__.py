"""CrowdStrike Falcon connector (read-only): hosts, alerts of a host, alert by id, open alerts.

API: OAuth2 client credentials (`/oauth2/token`), Hosts (`/devices/queries/devices/v1`,
`/devices/entities/devices/v2`) and Alerts (`/alerts/queries/alerts/v2`, `/alerts/entities/alerts/v2`,
which is a POST that only reads). MSSP (Flight Control): set the child CID.
API client scopes: Hosts: Read, Alerts: Read. Nothing else is needed or used.
"""

import time

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

PRODUCT = "CrowdStrike"
CLOUDS = {  # region -> (API, console)
    "us-1": ("https://api.crowdstrike.com", "https://falcon.crowdstrike.com"),
    "us-2": ("https://api.us-2.crowdstrike.com", "https://falcon.us-2.crowdstrike.com"),
    "eu-1": ("https://api.eu-1.crowdstrike.com", "https://falcon.eu-1.crowdstrike.com"),
    "us-gov-1": ("https://api.laggar.gcw.crowdstrike.com", "https://falcon.laggar.gcw.crowdstrike.com"),
}
HOST = r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}"
ALERT_ID = r"[0-9a-f]{32}:[a-z_]{2,20}:[0-9a-f]{32}:[0-9A-Za-z_-]{1,64}"
SEVERITY = {"low": 20, "medium": 40, "high": 60, "critical": 80}


class CrowdStrike(Connector):
    manifest = Manifest(name="crowdstrike", label=PRODUCT, version="1.0.0", type=EDR, vendor="CrowdStrike",
                        description="Falcon hosts and alerts: host details and containment state, alerts of a host, alert by id, open alerts.")
    config_schema = {
        "type": "object",
        "required": ["cloud", "client_id", "client_secret"],
        "properties": {
            "cloud": {"type": "string", "title": "Cloud", "enum": list(CLOUDS), "default": "us-1",
                      "enumLabels": ["US-1", "US-2", "EU-1", "US-GOV-1"]},
            "client_id": {"type": "string", "title": "API client ID", "maxLength": 200},
            "client_secret": {"type": "string", "title": "API client secret", "secret": True, "maxLength": 500},
            "member_cid": {"type": "string", "title": "Child CID (MSSP)", "maxLength": 64, "default": "",
                           "description": "Only for Flight Control: the customer's CID"},
        },
    }
    operations = (
        Operation("get_host", "Host", "Details of a host by name: OS, last seen, IPs, sensor version, containment state.",
                  DEVICE, {"host": Param("host name", pattern=HOST, max_length=253)}),
        Operation("host_alerts", "Alerts of a host", "Most recent alerts of a host (not closed), newest first.",
                  ALERT, {"host": Param("host name", pattern=HOST, max_length=253)}),
        Operation("get_alert", "Alert by id", "Read one alert by its composite id.", ALERT,
                  {"alert_id": Param("alert composite id", pattern=ALERT_ID, max_length=200)},
                  match={"alert_id": r"\b" + ALERT_ID + r"\b"}),
        Operation("open_alerts", "Open alerts", "Newest alerts still new or in progress, optionally from a minimum severity.",
                  ALERT, {"min_severity": Param("low, medium, high or critical", required=False,
                                                pattern=r"(?i)low|medium|high|critical")}),
    )

    # --- Contract -------------------------------------------------------------------------

    def _cloud(self, config: dict) -> tuple[str, str]:
        cloud = CLOUDS.get(config.get("cloud") or "us-1")
        if cloud is None:
            raise ConnectorError("CrowdStrike: unknown cloud", retryable=False, public=True)
        return cloud

    def origins(self, config: dict) -> list[str]:
        return [self._cloud(config)[0]]

    def read_posts(self, config: dict) -> list[str]:
        api = self._cloud(config)[0]
        return [api + "/oauth2/token", api + "/alerts/entities/alerts/v2", api + "/alerts/entities/alerts/v3"]

    def test_connection(self, ctx: Context) -> str:
        self._get(ctx, "/devices/queries/devices/v1", {"limit": "1"})
        return "Connected: hosts readable"

    def run(self, ctx: Context, operation: str, args: dict) -> list[Record]:
        if operation == "get_host":
            return [self._device(ctx, d) for d in self._hosts(ctx, args["host"])]
        if operation == "host_alerts":
            return self._alerts(ctx, f"device.hostname:'{_fql(args['host'])}'+status:!'closed'")
        if operation == "get_alert":
            return [self._alert(ctx, a) for a in self._alert_entities(ctx, [args["alert_id"]])]
        if operation == "open_alerts":
            flt = "status:['new','in_progress']"
            sev = SEVERITY.get((args.get("min_severity") or "").lower())
            if sev:
                flt += f"+severity:>={sev}"
            return self._alerts(ctx, flt)
        raise ConnectorError(f"Unknown operation {operation}", retryable=False)

    # --- Requests --------------------------------------------------------------------------

    def _token(self, ctx: Context) -> str:
        st = ctx.state
        if st.get("token") and st.get("expires", 0) > time.time() + 30:
            return st["token"]
        if not ctx.config.get("client_id") or not ctx.secrets.get("client_secret"):
            raise ConnectorError("CrowdStrike: API client ID or secret missing", retryable=False, public=True)
        data = {"client_id": ctx.config["client_id"], "client_secret": ctx.secrets["client_secret"]}
        if ctx.config.get("member_cid"):
            data["member_cid"] = ctx.config["member_cid"]
        r = ctx.http.request("POST", self._cloud(ctx.config)[0] + "/oauth2/token", data=data, headers={"Accept": "application/json"})
        if r.status not in (200, 201):
            raise status_error(PRODUCT + " (token)", r.status)
        body = r.json() or {}
        if not isinstance(body.get("access_token"), str):
            raise ConnectorError("CrowdStrike: no token in the answer", retryable=False)
        st["token"], st["expires"] = body["access_token"], time.time() + float(body.get("expires_in") or 1799)
        return st["token"]

    def _call(self, ctx: Context, method: str, path: str, **kw) -> dict:
        url = self._cloud(ctx.config)[0] + path
        for attempt in (1, 2):
            headers = {"Accept": "application/json", "Authorization": f"Bearer {self._token(ctx)}"}
            r = ctx.http.request(method, url, headers=headers, **kw)
            if r.status == 401 and attempt == 1:
                ctx.state.clear()  # token revoked or expired early: one new token
                continue
            break
        if r.status != 200:
            raise status_error(PRODUCT, r.status)
        body = r.json()
        if not isinstance(body, dict):
            raise ConnectorError("CrowdStrike returned an unexpected answer")
        return body

    def _get(self, ctx: Context, path: str, params: dict) -> dict:
        return self._call(ctx, "GET", path, params=params)

    def _hosts(self, ctx: Context, host: str) -> list[dict]:
        ids = self._get(ctx, "/devices/queries/devices/v1", {"filter": f"hostname:'{_fql(host)}'", "limit": "5"}).get("resources") or []
        if not ids:
            return []
        return self._get(ctx, "/devices/entities/devices/v2", {"ids": [i for i in ids if isinstance(i, str)][:5]}).get("resources") or []

    def _alert_entities(self, ctx: Context, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        try:
            body = self._call(ctx, "POST", "/alerts/entities/alerts/v2", json={"composite_ids": ids})
        except ConnectorError as e:
            if "404" not in str(e):
                raise
            body = self._call(ctx, "POST", "/alerts/entities/alerts/v3", json={"composite_ids": ids})
        return [a for a in body.get("resources") or [] if isinstance(a, dict)]

    def _alerts(self, ctx: Context, flt: str) -> list[Record]:
        ids = self._get(ctx, "/alerts/queries/alerts/v2", {"filter": flt, "sort": "created_timestamp.desc", "limit": "5"}).get("resources") or []
        return [self._alert(ctx, a) for a in self._alert_entities(ctx, [i for i in ids if isinstance(i, str)][:5])]

    # --- Records ---------------------------------------------------------------------------

    def _host_url(self, ctx: Context, device_id: str) -> str | None:
        return f"{self._cloud(ctx.config)[1]}/hosts/hosts/host/{device_id}" if device_id.isalnum() else None

    def _device(self, ctx: Context, d: dict) -> Record:
        status = d.get("status") or ""
        fields = {
            "Containment": {"contained": "contained (network isolated)", "containment_pending": "containment pending",
                            "lift_containment_pending": "lifting containment", "normal": "not contained"}.get(status, status),
            "OS": clip(" ".join(x for x in (d.get("os_version"), d.get("os_build")) if x) or d.get("platform_name"), 120),
            "Type": clip(d.get("product_type_desc"), 60),
            "Last seen": clip(d.get("last_seen"), 40), "First seen": clip(d.get("first_seen"), 40),
            "Local IP": clip(d.get("local_ip"), 60), "External IP": clip(d.get("external_ip"), 60),
            "MAC": clip(d.get("mac_address"), 40), "Sensor version": clip(d.get("agent_version"), 40),
            "Domain": clip(d.get("machine_domain"), 120), "OU": clip(", ".join(d.get("ou") or []), 200),
            "Site": clip(d.get("site_name"), 120), "Tags": clip(", ".join(d.get("tags") or []), 200),
            "Device id": clip(d.get("device_id"), 64),
        }
        device_id = str(d.get("device_id") or "")
        return Record(kind=DEVICE, id=clip(d.get("hostname"), 253) or device_id, title=clip(d.get("system_product_name"), 120),
                      url=self._host_url(ctx, device_id), fields={k: v for k, v in fields.items() if v},
                      updated=clip(d.get("modified_timestamp"), 40) or None)

    def _alert(self, ctx: Context, a: dict) -> Record:
        dev = a.get("device") if isinstance(a.get("device"), dict) else {}
        technique = " ".join(x for x in (a.get("technique_id"), a.get("technique")) if x)
        fields = {
            "Severity": clip(a.get("severity_name") or a.get("severity"), 40), "Status": clip(a.get("status"), 40),
            "Host": clip(dev.get("hostname"), 253), "User": clip(a.get("user_name"), 120),
            "Tactic": clip(a.get("tactic"), 80), "Technique": clip(technique, 120),
            "File": clip(a.get("filename"), 200), "Command line": clip(a.get("cmdline"), 300),
            "Created": clip(a.get("created_timestamp"), 40), "Assigned to": clip(a.get("assigned_to_name"), 120),
        }
        links = {}
        device_id = str(dev.get("device_id") or "")
        if device_id and self._host_url(ctx, device_id):
            links[f"Host {dev.get('hostname') or device_id}"] = self._host_url(ctx, device_id)
        link = a.get("falcon_host_link")
        console = self._cloud(ctx.config)[1]
        return Record(kind=ALERT, id=clip(a.get("composite_id") or a.get("id"), 200),
                      title=clip(a.get("display_name") or a.get("name"), 200),
                      url=link if isinstance(link, str) and link.startswith(console + "/") else None,
                      fields={k: v for k, v in fields.items() if v}, text=clip(a.get("description"), 1500) or None,
                      updated=clip(a.get("updated_timestamp"), 40) or None, links=links)


def _fql(value: str) -> str:
    """A value inside FQL single quotes (host names are already restricted to [A-Za-z0-9._-])."""
    return value.replace("\\", "").replace("'", "")


connector = CrowdStrike()
