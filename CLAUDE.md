# Mentis – development conventions

Read `docs/DESIGN.md` before changing anything. It is the source of truth for scope and decisions.

## Rules

- **English only** in the repository: code, comments, docs, commit messages, UI strings.
- **Update `CHANGELOG.md` on every commit** (under `[Unreleased]`), so another session can resume the work.
- **Keep docs current:** `INSTALL.md`, `docs/DESIGN.md` and the in-app Help (`frontend/src/help/<profile>/*.md`, which are also the manuals) must reflect the latest implementation. A feature is not done until its help topic is written or updated.
- **Pull requests only:** work on a branch, open a PR, the owner merges. Never push to `main` directly.
- **Modular code:** no monolithic files; one responsibility per module or component.
- **Tenant isolation is server-side:** every query and integration call filters by the tenant stored on the chat or the request context, never by client input alone.
- **Read-only integrations:** connectors expose read operations only.
- **Plugins:** integrations live in `plugins/<name>/` and implement the core connector contract; the core never imports a specific plugin.
- **UI:** three themes (Light, Medium, Dark); one inline-SVG icon family (same stroke width, round caps/joins, `currentColor`); no emoji as icons.
- **Releases:** the owner tests in the lab and tags versions (first: `0.1.0`). Each release note includes the full upgrade command block for the VPS and a post-upgrade check.

## Layout

```
backend/    FastAPI API, ingestion worker, core services
frontend/   React app (chat, tenant admin, platform admin, account)
plugins/    Connector plugins (servicenow/, jira/, defender/, ...)
assets/     Logo and static brand assets
docs/       Design document and manuals
```
