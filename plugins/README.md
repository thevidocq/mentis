# Plugins

Each integration (ticketing, EDR, SIEM) is a plugin in its own folder, implementing the core connector contract described in `docs/DESIGN.md` (Integrations → Plugin model).

- One folder per product: `plugins/servicenow/`, `plugins/jira/`, `plugins/defender/`, ...
- Read-only operations only.
- Registered through the `mentis.connectors` Python entry point.
- Added through pull requests and shipped with releases.
