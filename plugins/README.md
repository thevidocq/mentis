# Plugins

Each integration (ticketing, EDR, SIEM, identity) is a plugin in its own folder, implementing the core connector contract (`backend/app/connectors/contract.py`, described in `docs/DESIGN.md`, Integrations → Plugin model). The core never imports a specific plugin.

| Folder | Product | Type | Operations |
| --- | --- | --- | --- |
| `servicenow/` | ServiceNow | ticketing | ticket by number, search, open tickets of a host |
| `jira/` | Jira Cloud and Data Center | ticketing | issue by key, search, open issues of a host |
| `crowdstrike/` | CrowdStrike Falcon | edr | host, alerts of a host, alert by id, open alerts |
| `defender/` | Microsoft Defender for Endpoint | edr | device, alerts of a device, alert by id, open alerts, IP statistics |
| `entraid/` | Microsoft Entra ID | identity | user (state, MFA, risk, last sign-in), recent sign-ins of a user, users at risk |
| `trendmicro_visionone/` | Trend Vision One | edr | endpoint, Workbench alerts of an endpoint, alert by id, open alerts |

## Writing a plugin

- A Python package with a `pyproject.toml` that registers the connector under the `mentis.connectors` entry point (the name must equal `manifest.name`). Standard library only: no dependencies.
- Subclass `Connector`: `manifest`, `config_schema` (JSON Schema; `"secret": true` for credentials), `operations` (read-only, typed parameters with patterns; `match` only for identifiers with an unmistakable shape), `origins()`, `read_posts()` (POST URLs that only read, e.g. token endpoints), `test_connection()`, `run()` returning `Record`s with the link to the record in the product.
- Never call the network yourself: use `ctx.http`. The core refuses writes, other addresses and redirects, and caps time, requests and size.
- Errors: raise `ConnectorError`; use `status_error()` so reply bodies (which may echo secrets) never reach messages.
- Tests in `<plugin>/tests/`, with the `fake_http` fixture of `plugins/conftest.py`. Run all of them with `python -m pytest plugins/`.
- Added through pull requests and shipped with releases. Write the tenant admin's setup notes in `frontend/src/help/tenant-admin/06-integrations.md`.
