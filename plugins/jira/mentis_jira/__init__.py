"""Jira connector (read-only), Cloud and Data Center: issues by key, search, open issues of a host.

Cloud: REST API v3 (`/rest/api/3/issue`, `/rest/api/3/search/jql`), e-mail and API token.
Data Center: REST API v2 (`/rest/api/2/issue`, `/rest/api/2/search`), personal access token.
Permissions: an account with Browse projects on the projects Mentis may read; list them in
Projects to limit searches and key lookups to them.
"""

import base64
import re

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

PRODUCT = "Jira"
# Words shaped like issue keys that are not: standards, hashes, other products' ids.
NOT_KEYS = ("CVE|CWE|CAPEC|SHA|MD|TLS|SSL|RFC|ISO|IEC|AES|RSA|UTF|TCP|UDP|HTTP|HTTPS|IPV|COVID|KB|MS|NIS|PCI|GDPR|"
            "WB|INC|SIR|CHG|PRB|RITM|SCTASK|TASK|WIN|OWASP|NIST|CIS")
KEY = r"[A-Z][A-Z0-9_]{1,9}-\d{1,7}"
HOST = r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}"
BASE_FIELDS = ["summary", "status", "priority", "issuetype", "assignee", "reporter", "created", "updated", "labels",
               "components", "resolution", "description", "comment", "project"]


def _name(v) -> str:
    """Display text of a Jira field value (object, list, string)."""
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(x for x in (_name(i) for i in v[:20]) if x)
    if isinstance(v, dict):
        for k in ("displayName", "name", "value", "key"):
            if isinstance(v.get(k), str):
                return v[k]
        if v.get("type") == "doc":
            return adf_text(v)
        return ""
    return str(v)


def adf_text(node, out: list | None = None) -> str:
    """Plain text of an Atlassian Document Format value (Cloud descriptions and comments)."""
    top = out is None
    out = [] if out is None else out
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            out.append(node["text"])
        elif node.get("type") in ("mention", "emoji") and isinstance(node.get("attrs"), dict):
            out.append(str(node["attrs"].get("text") or ""))
        elif node.get("type") == "hardBreak":
            out.append("\n")
        for child in node.get("content") or []:
            adf_text(child, out)
        if node.get("type") in ("paragraph", "heading", "listItem", "codeBlock", "blockquote"):
            out.append("\n")
    elif isinstance(node, list):
        for child in node:
            adf_text(child, out)
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip() if top else ""


def _words(text: str) -> str:
    """Search words for JQL `text ~ "..."`: letters, digits, dots, @ and _ only."""
    return " ".join(re.sub(r"[^\w\s.@]", " ", text).split())[:100]


class Jira(Connector):
    manifest = Manifest(name="jira", label=PRODUCT, version="1.0.0", type=TICKETING, vendor="Atlassian",
                        description="Jira Cloud or Data Center issues: read by key, search, open issues of a host.")
    config_schema = {
        "type": "object",
        "required": ["site_url", "deployment"],
        "properties": {
            "site_url": {"type": "string", "format": "uri", "title": "Site URL", "maxLength": 300,
                         "description": "e.g. https://acme.atlassian.net or https://jira.acme.local"},
            "deployment": {"type": "string", "title": "Deployment", "enum": ["cloud", "datacenter"], "default": "cloud",
                           "enumLabels": ["Jira Cloud", "Jira Data Center / Server"]},
            "email": {"type": "string", "title": "Account e-mail", "maxLength": 320, "showIf": {"deployment": "cloud"}},
            "api_token": {"type": "string", "title": "API token", "secret": True, "maxLength": 500, "showIf": {"deployment": "cloud"}},
            "pat": {"type": "string", "title": "Personal access token", "secret": True, "maxLength": 500,
                    "showIf": {"deployment": "datacenter"}},
            "projects": {"type": "string", "title": "Projects", "maxLength": 300, "default": "",
                         "description": "Project keys Mentis may read, comma separated (e.g. SOC, SEC). Empty = every project the account can browse."},
            "extra_fields": {"type": "string", "title": "Extra fields", "maxLength": 500, "default": "",
                             "description": "Field mapping: more fields to read, comma separated (e.g. customfield_10010)"},
        },
    }
    operations = (
        Operation("get_issue", "Issue by key", "Read one issue by its key (e.g. SOC-123).", TICKET,
                  {"key": Param("issue key, e.g. SOC-123", pattern=r"(?i)" + KEY)},
                  match={"key": r"\b(?!(?:" + NOT_KEYS + r")-)" + KEY + r"\b"}),
        Operation("search_issues", "Search issues", "Search issues by words in summary, description and comments, newest first.",
                  TICKET, {"query": Param("search words", max_length=100, identifier=False),
                           "scope": Param("open (default) or all", required=False, pattern=r"(?i)open|all")}),
        Operation("issues_for_host", "Open issues of a host", "Open issues that mention a host name.",
                  TICKET, {"host": Param("host name", pattern=HOST, max_length=253)}),
    )

    # --- Contract -------------------------------------------------------------------------

    def origins(self, config: dict) -> list[str]:
        return [origin_of(config.get("site_url", ""))]

    def test_connection(self, ctx: Context) -> str:
        me = self._get(ctx, "/myself", {})
        who = me.get("displayName") or me.get("emailAddress") or me.get("name") or "account"
        return f"Connected as {clip(who, 80)}"

    def run(self, ctx: Context, operation: str, args: dict) -> list[Record]:
        if operation == "get_issue":
            key = args["key"].upper()
            projects = self._projects(ctx)
            if projects and key.split("-")[0] not in projects:
                return []  # a key of a project Mentis may not read
            try:
                issue = self._get(ctx, f"/issue/{key}", {"fields": ",".join(self._fields(ctx))})
            except ConnectorError as e:
                if "404" in str(e):
                    return []
                raise
            return [self._record(ctx, issue)]
        if operation == "search_issues":
            words = _words(args["query"])
            if not words:
                return []
            open_only = (args.get("scope") or "open").lower() == "open"
            return self._search(ctx, f'text ~ "{words}"', open_only)
        if operation == "issues_for_host":
            return self._search(ctx, f'text ~ "{_words(args["host"])}"', True)
        raise ConnectorError(f"Unknown operation {operation}", retryable=False)

    # --- Requests --------------------------------------------------------------------------

    def _cloud(self, ctx: Context) -> bool:
        return (ctx.config.get("deployment") or "cloud") == "cloud"

    def _api(self, ctx: Context) -> str:
        return base_url(ctx.config["site_url"]) + ("/rest/api/3" if self._cloud(ctx) else "/rest/api/2")

    def _auth(self, ctx: Context) -> dict:
        if self._cloud(ctx):
            if not ctx.config.get("email") or not ctx.secrets.get("api_token"):
                raise ConnectorError("Jira: account e-mail or API token missing", retryable=False, public=True)
            raw = f"{ctx.config['email']}:{ctx.secrets['api_token']}".encode()
            return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
        if not ctx.secrets.get("pat"):
            raise ConnectorError("Jira: personal access token missing", retryable=False, public=True)
        return {"Authorization": f"Bearer {ctx.secrets['pat']}"}

    def _get(self, ctx: Context, path: str, params: dict) -> dict:
        r = ctx.http.request("GET", self._api(ctx) + path, params=params, headers={"Accept": "application/json", **self._auth(ctx)})
        if r.status != 200:
            raise status_error(PRODUCT, r.status)
        data = r.json()
        if not isinstance(data, dict):
            raise ConnectorError("Jira returned an unexpected answer")
        return data

    def _projects(self, ctx: Context) -> list[str]:
        keys = [k.strip().upper() for k in (ctx.config.get("projects") or "").split(",")]
        return [k for k in keys if re.fullmatch(r"[A-Z][A-Z0-9_]{1,9}", k)]

    def _fields(self, ctx: Context) -> list[str]:
        extra = [f.strip() for f in (ctx.config.get("extra_fields") or "").split(",")]
        return list(dict.fromkeys(BASE_FIELDS + [f for f in extra if re.fullmatch(r"[A-Za-z0-9_]{1,80}", f)]))

    def _search(self, ctx: Context, condition: str, open_only: bool) -> list[Record]:
        jql = condition
        if open_only:
            jql += " AND statusCategory != Done"
        projects = self._projects(ctx)
        if projects:
            jql += f" AND project in ({', '.join(projects)})"
        jql += " ORDER BY updated DESC"
        path = "/search/jql" if self._cloud(ctx) else "/search"
        data = self._get(ctx, path, {"jql": jql, "fields": ",".join(self._fields(ctx)), "maxResults": "5"})
        return [self._record(ctx, i) for i in (data.get("issues") or [])[:5] if isinstance(i, dict)]

    def _record(self, ctx: Context, issue: dict) -> Record:
        f = issue.get("fields") or {}
        key = str(issue.get("key") or "")
        fields = {}
        for label, name in (("Status", "status"), ("Priority", "priority"), ("Type", "issuetype"), ("Assignee", "assignee"),
                            ("Reporter", "reporter"), ("Resolution", "resolution"), ("Labels", "labels"),
                            ("Components", "components"), ("Created", "created"), ("Project", "project")):
            value = clip(_name(f.get(name)), 300)
            if value:
                fields[label] = value
        for name in self._fields(ctx):
            if name not in BASE_FIELDS and _name(f.get(name)):
                fields[name] = clip(_name(f.get(name)), 300)
        description = f.get("description")
        text = []
        if description:
            text.append("Description: " + (adf_text(description) if isinstance(description, dict) else str(description))[:1500])
        comments = ((f.get("comment") or {}).get("comments") or [])[-3:] if isinstance(f.get("comment"), dict) else []
        for c in comments:
            body = c.get("body")
            body = adf_text(body) if isinstance(body, dict) else str(body or "")
            text.append(f"Comment by {_name(c.get('author')) or 'unknown'} ({c.get('created', '')[:16]}): {body[:500]}")
        return Record(kind=TICKET, id=key, title=clip(f.get("summary"), 300),
                      url=f"{base_url(ctx.config['site_url'])}/browse/{key}" if re.fullmatch(KEY, key) else None,
                      fields=fields, text="\n".join(text) or None, updated=str(f.get("updated") or "")[:25] or None)


connector = Jira()
