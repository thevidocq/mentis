# Changelog

All notable changes to this project are documented here. Every commit updates this file so that work can be resumed from any session.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Fixed
- Login lockout: failed attempts are counted in the database, so parallel password or code guesses can no longer slip past the limit.
- 2FA: a code is stored as used atomically, so the same code sent twice in parallel signs in only once.
- 2FA: a code with non-ASCII digits or a challenge with non-ASCII characters is refused (401) instead of causing a server error.
- Login: disabled and locked accounts take as long to answer as others, so response time no longer reveals them.
- Invitations: an expired pending invitation from another admin no longer blocks inviting the same email again.
- PDFs that only restrict printing or copying (no password to open) were refused as password-protected; they are now read. A PDF that needs a password fails in the worker with "The file is password-protected".
- Excel cells formatted but never filled (often whole rows up to column XFD) turned a sheet into thousands of empty table columns, flooding chunks and answers; empty columns are now dropped.
- A version processed late (queued again after a Redis outage, or retried) replaced a newer version already in use; it now stays inactive and can be restored.
- Reindex requested while Redis was down gave a server error and left the state "queued", blocking every later reindex; it now answers 503 and can be requested again.
- LLM answers with raw line breaks inside the JSON (common with local models) were shown to analysts as raw JSON; follow-ups sent as a string became one chip per letter; an answer cut by the token limit is now shown as text.
- An LLM reply with an unexpected shape (not a JSON object, content as a list of parts) gave a server error in the chat; it is now read or reported as a provider error.
- An API key echoed back by an LLM or embedding endpoint in an error body reached the chat, logs and status page; it is now redacted.
### Changed
- **Docker builds reuse their cache across releases**: system packages (Tesseract) and Python dependencies are installed from a list extracted from `pyproject.toml` before the app code is copied, and `npm ci` runs on `package.json`/`package-lock.json` with the version blanked; a version bump or a code change no longer reinstalls them (the first build after this change still installs everything once).

### Fixed
- Web proxy: the API is resolved at request time under its own alias `mentis-api`; before, `docker compose up -d api` could leave the web container on the old IP (502), and joining `equalizer_edge` could send `/api/` to another stack's `api` service.
- `restore.sh --with-env` replaced `.env` before the RESTORE confirmation (a cancelled restore kept the swapped secrets), and left the database role on its old password; on a new server it failed when the `api` container did not exist yet.
- `backup.sh` aborted the whole backup when a MinIO file changed while being archived (GNU tar exit 1).
- `check.sh` reported OK after a failed upgrade build (old containers still running): it now checks that the API version matches the checkout; it also read `MENTIS_WEB_PORT` wrong from a `.env` with CRLF or single quotes and ignored `MENTIS_WEB_BIND`.
- Syslog: a collector host name that cannot be encoded (e.g. `collector..local`) stopped the forwarding thread for good and made the Test button fail with an error 500; UDP messages cut at 8000 bytes could end in half a UTF-8 character.
- Log CSV export: cells starting with a tab or carriage return were not neutralised against spreadsheet formulas.
- Configuration import: syslog, SMTP and embedding values and AI provider options (e.g. a price as text, which broke the usage page) were not validated, keys such as `indexed_model` were imported, a non-text tenant name gave an error 500, and the dry run reported "not found" for AI providers added by the same file.
- `backups/` is ignored by git (backups contain `.env`); the nginx example in INSTALL.md waits 300 s for the API, like the web container.

## [0.3.0] - 2026-11-25

### Added
- **Granular access**: tenant admins and analysts see only the customers ticked on their account. **General** (the shared documentation) is ticked by default and can be removed. **All customers, including future ones** gives every customer, also those created later. Chat scopes, retrieval, documents, LLM, usage and logs all follow the same rules (`services/access.py`), checked again on every question.
- Tenant admins invite and edit **tenant admins and analysts**, only with customers they have themselves (all customers only if they have all). Users they cannot manage are not listed. A tenant admin cannot change its own role or customers. Changing a user's customers signs them out everywhere.
- **General is managed by tenant admins** who have it, from the usual Documents page; every action is logged with the user.
- Per customer, the super-admin decides whether its tenant admins may choose the LLM (`admin_can_set_llm`, default on); when off, the LLM page is read-only.
- Migration 0008: `all_tenants` on users and invitations. Existing analysts get **All customers** (as before); existing tenant admins and their pending invitations also get General.

- **General as a chat scope**: `@` ends with **General**, to ask the shared documentation alone (tenant admins test it; users with only General can chat).
- **Log out like Equalizer**: the account card at the bottom of every menu has Help (?) and a red Log out button, with the version underneath.

### Changed
- **The super-admin no longer uses the chat or manages documents**: platform management only. The General documentation page left the platform menu.
- Tenant admins see AI providers only as name and model (no URL, no prices) and LLM usage without costs.

### Fixed
- **TOTP codes could be replayed** within their 90-second window (e.g. a code seen over a shoulder): each code now works once (migration 0006). A still-valid enrollment step can no longer replace an authenticator already set up.
- **Wrong current password** on password change was not counted: it now counts like a failed sign-in (5 lock the account and end the session).
- **Document versions stuck** in Processing after a worker crash or restart stayed there forever: after the ingestion timeout they become Failed ("Processing was interrupted", use Retry); versions Queued whose job was lost are queued again (migration 0007, checked every 10 minutes by the worker).
- Expired sign-in sessions and invitations expired for a week were never deleted: removed by the daily purge.
- When the session expires or is revoked, the app now returns to the sign-in page instead of showing "Not authenticated" errors.
- Blank names (only spaces) were accepted for users, invitations and chat titles.
- Document pipeline review:
  - a reindex with no documents never recorded the new embedding model, so every later upload failed asking for a reindex;
  - after an embedding model change without reindex, questions failed with a server error: they now get a clear "run Reindex" answer;
  - Qdrant unreachable or refusing a query gave a server error in the chat and in "test a question": now a readable error answer / 503;
  - an upload failed with a server error when Redis was down although the file was stored: it now stays Queued and the worker's recovery queues it again;
  - a single huge table row (a long Excel cell) became one oversized chunk that the embedding service could refuse, failing the whole document: it is now split with the header repeated; the local embedding service also runs with `--auto-truncate`;
  - index points of a version deleted while processing are removed.
- Documents: Word content controls (common in corporate templates) and PowerPoint grouped shapes were skipped, so their text never reached the answers; a PDF page with a broken text layer failed the whole document (now read with OCR).
- Worker: a job process could reuse the database connections of the worker's maintenance thread after the fork (protocol errors under load); each job now opens its own. A failed daily purge is retried at the next hourly check instead of the next day.
- Chat: after a failed answer the next question sent two user turns in a row to the LLM (some providers refuse it); history is now clean user/assistant pairs. An empty LLM answer is shown as "not found". A document can no longer close its own passage in the prompt.
- Invitations: a tenant admin could replace another admin's pending invitation for the same email; an invitation whose customers were all deleted created a user without customers.
- Configuration import: malformed files (wrong types, missing retention values) caused a server error instead of a clear message.
- Web: "Mentis cannot be reached" instead of "Failed to fetch" when offline; a clear message for files too large for the proxy; a temporary error on the Documents page clears at the next refresh.
- These fixes (second bugfix round) were listed under 0.2.0 but did not make it into that release.

## [0.2.0] - 2026-11-25

### Added
- **Tenant admins of several customers**: invitations and user edit pick one or more customers; a customer selector in the tenant area; `@` in chat lists their customers plus **All my customers** (only theirs, with General). Migration 0005 moves every existing tenant admin to the new model (`user_tenants`, `invitations.tenant_ids`).
- **Phone layout**: the menu and the chat history open as drawers from a top bar (☰); tables become one card per row; full-width chat; 16 px inputs (no zoom on iOS); bottom-sheet dialogs.
- **`create-admin` command** (`docker compose exec api python -m app.cli create-admin`). The browser setup page is off by default (`MENTIS_WEB_SETUP=false`): a fresh public install cannot be claimed by whoever opens it first.
- `MENTIS_WEB_PORT` (default 8080); `check.sh` reads it from `.env`.
- INSTALL: publishing behind the Caddy of Equalizer on the same VPS.
- A one- or two-word message without matching documents ("ciao") gets a hint on what to ask, still without calling the LLM.

### Changed
- Only the web container publishes a host port. API, PostgreSQL, Qdrant, MinIO and Redis no longer bind 127.0.0.1 ports (no conflicts with other stacks, nothing exposed). `check.sh` asks the API from inside its container.
- `MENTIS_TRUSTED_PROXIES` defaults to private networks instead of `*`.

### Fixed
- Security headers (CSP, X-Frame-Options, ...) were missing on the pages and assets themselves: nginx dropped them in locations with their own headers. Now included everywhere; checked with a real nginx and a CSP-violation watch.
- The client IP in Logs could be spoofed with an `X-Forwarded-For` header sent by the client.
- Interactive API docs (`/api/docs`, `/api/openapi.json`) were public; now off unless `MENTIS_API_DOCS=true`.
- Syslog forwarding could lose events raised inside ingestion jobs (forked processes); they are now sent synchronously there.
- Stray files removed from the repository (a shellcheck wheel).

## [0.1.1] - 2026-11-25

### Fixed
- Installation failed with `pull access denied for minio/minio`: MinIO, Inc. deleted its free images from Docker Hub. The `minio` service now uses `pgsty/minio` (community fork, drop-in: same data format and settings), pinned to `RELEASE.2026-03-25T00-00-00Z`.

## [0.1.0] - 2026-11-25

First release. Everything below this heading, down to the end of the file, is part of it.

### Added
- **Logs** (super-admin): audit and system events with period, type, level, tenant and action filters, search, details per row, CSV export (formula-safe, logged). Chat events stay metadata-only.
- **Syslog forwarding** to a SIEM: RFC 5424 with JSON details, UDP, TCP or TLS (RFC 6587 octet counting), background sending with a bounded queue (a dead collector never slows requests), test button, status line with sent/dropped/last error.
- **Retention** for chats and log events (default 1 year, or keep forever); daily purge in the worker (one replica per day via a Redis lock) and **Purge now**.
- **LLM usage** per customer and model: questions, answered/not found/errors, tokens, average time, estimated cost from optional per-provider prices. Tenant admins see their own on the LLM page.
- **Backup and configuration**: `backup.sh` / `restore.sh` (PostgreSQL dump, MinIO and Qdrant volumes, `.env`, checksums; restore asks for confirmation, `--with-env` for a new server); configuration export/import as JSON without secrets, with a dry run listing the changes before applying.
- Help: Logs, Retention, LLM usage, Backup and configuration; updated getting started, operations, AI providers, tenant LLM.
- Version 0.1.0; release notes `docs/releases/v0.1.0.md`.
- **Chat** (0.1.0 part 4): analysts ask questions and get answers only from the documentation in use, with numbered citations (customer, document, version, page, passage). `@` chooses the customer (All customers by default) and the first message locks it; typing `@` afterwards shows the list greyed. `#` integrations are shown as coming.
- Answer pipeline: customer + General (tenant setting) or every active customer; no matching passage → "Not found" without calling the LLM; anti-hallucination system prompt, passages treated as untrusted data; JSON answer with lenient parsing; citations validated against the passages sent; up to 3 follow-ups (tenant setting); automatic title from the first exchange (kept once renamed); last turns sent as context.
- History sidebar grouped by day with search (titles and messages), rename and delete; feedback thumbs; copy; model name and latency under each answer; Retry on errors; disabled customers make their chats read-only.
- Chats are private to their user. Analysts and super-admins can chat on any customer; tenant admins only on their own (to test). Logs record metadata only (model, tokens, latency, passages), never questions or answers.
- **AI providers** (super-admin): Anthropic Messages, OpenAI Chat Completions (OpenAI, Ollama, vLLM) and OpenAI Responses (gpt-oss, Daybreak Blue) with presets, encrypted API keys, test, platform default. Per-tenant LLM and fallback (tenant admin **LLM** page, brain icon in Tenants); automatic failover.
- Settings `MENTIS_CHAT_PASSAGES` (8) and `MENTIS_CHAT_MIN_SCORE` (0.3); `api` can reach model servers on the host via `host.docker.internal`.
- Service status: one line per AI provider (lists models: checks address and key, no tokens spent).
- Tenant deletion and user deletion also remove the related chats.
- Help: Using the chat (analyst), LLM and testing answers (tenant admin), AI providers (super-admin); updated getting started, tenants, roles.
- Migration 0004.
- README rewritten with features and screenshots (`docs/screenshots/`, fictional demo data).
- Release notes for v0.1.0-alpha.2 (`docs/releases/v0.1.0-alpha.2.md`).
- **Indexing** (0.1.0 part 3b): chunks embedded through any OpenAI-compatible endpoint and stored in Qdrant, one collection per customer. New `embeddings` container (Hugging Face TEI, CPU) with BAAI/bge-m3 by default.
- Indexing is the last ingestion step; a version that cannot be indexed fails and never replaces the active one. Activation, approval, restore, deletion and tenant deletion keep Qdrant in sync.
- Retrieval service (customer + General, active versions only) with every hit re-checked against PostgreSQL, ready for the chat.
- Preview: **Test a question** shows the passages of that version Mentis would use, with match score and page.
- **Embedding and Qdrant** page (super-admin): endpoint, model, API key (encrypted), test connection, index stats, model-change detection and **Reindex everything** with progress.
- Service status adds Qdrant and Embeddings.
- Workers: `MENTIS_WORKER_REPLICAS`; `check.sh` checks every replica.
- Help: Embedding and Qdrant (super-admin), Test a question, scaling.
- **Documents** (0.1.0 part 3a): upload with validation (PDF/DOCX/PPTX/XLSX only, content must match extension, macro-enabled/encrypted/old formats refused, zip-bomb guard, 50 MB limit, sanitized names); originals in MinIO; versions by file name; identical re-upload refused.
- Ingestion worker (`worker` container, RQ on Redis, OCR with Tesseract eng+ita, CPU/RAM limits): per-page Markdown text with tables, PDF page images, OCR confidence, quality flags, chunks per page for the coming index. Optional Docling parser behind `MENTIS_PARSER=docling` (not verified yet).
- Version lifecycle: active version per document, approval before publishing (tenant setting), reject, make an older version active, retry failed; a failed or rejected version never replaces the active one.
- Documents UI for tenant admins and **General documentation** for super-admins: drag-and-drop upload, versions, rename, delete, download original; **preview** with original page next to extracted text, OCR badges and warnings, approve/reject.
- Service status now reports PostgreSQL, MinIO, Redis queue and the ingestion worker (`GET /api/platform/status`).
- Tenant deletion also removes documents, versions, pages, chunks and stored files.
- Help: Documents (tenant admin), General documentation (super-admin), updated status/operations.
- Migration 0003.
- Backend foundation: FastAPI app, settings, SQLAlchemy models (tenants, users, auth sessions, log events), Alembic initial migration (applied automatically at container start).
- First-run setup (`POST /api/setup`): creates the General tenant and the first super-admin, only once.
- Login with mandatory TOTP 2FA: password step, enrollment on first login, code verification; server-side sessions in an HttpOnly SameSite=Strict cookie; logout; current user; password change (signs out other sessions).
- Account lockout after 5 failed attempts (15 minutes); generic error messages.
- TOTP secrets encrypted at rest; session tokens stored hashed.
- Role guards (super_admin, tenant_admin, analyst).
- CSRF protection: state-changing API calls require the `X-Mentis-Request: 1` header.
- Log events (audit/system) for setup, login, 2FA, logout, password change.
- Operator CLI: `reset-2fa`, `unlock`.
- API service in Docker Compose, backend Dockerfile, `check.sh` post-install/upgrade check.
- Tenants API: list (analysts see all, tenant admins only their own), create with unique slug, rename/status (super-admin), settings (super-admin or own tenant admin), delete confirmed by typing the exact name; General cannot be deleted or disabled.
- Users API: list, update (name, role, tenant, active), delete, reset 2FA; tenant admins manage only admins of their own tenant; the last active super-admin is protected; deactivation and role change revoke sessions.
- Invitations: email invite with a 72-hour single-use link (token stored hashed); a new invite replaces a pending one; revocation; public accept endpoint sets the password. Without SMTP, the link is returned to the inviting admin to share manually.
- SMTP settings (super-admin): host, port, STARTTLS/SSL/none, username, encrypted password (never returned), sender; test email.
- Account: profile name and theme preference (light, medium, dark) via `PATCH /api/auth/me`.
- Migration 0002: invitations, platform settings, user preferences.
- `MENTIS_PUBLIC_URL` setting for invitation links.
- Backend test suite (27 tests).
- Web interface (React + Vite + TypeScript) served by an nginx `web` container on `127.0.0.1:8080`, proxying `/api`:
  - first-run setup, two-step sign-in with QR-code TOTP enrollment, invitation acceptance;
  - platform admin with left menu: Tenants (onboard, edit, delete with typed-name confirmation, General locked), Users (invite, edit role/tenant/active, reset 2FA, delete, pending invitations), Email (SMTP) with test email, Service status (API and database);
  - tenant admin: Users (own tenant admins), Settings (include General, approval before publishing, suggested follow-ups);
  - account page: profile edit, Light/Medium/Dark theme (saved per user), password change, 2FA status, sign out;
  - chat placeholder for analysts; upcoming sections marked "soon".
- In-app **Help**, one guide per profile (super-admin, tenant admin, analyst) plus common topics; super-admins also see the other guides. Source in `frontend/src/help/*.md`, indexed in `docs/MANUALS.md`.
- `GET /api/auth/me` now includes `tenant_name`.
- `check.sh` also checks the web container and the `/api` proxy.

## [0.0.0] – repository bootstrap

### Added
- Project design document (`docs/DESIGN.md`).
- Logo assets (`assets/logo/`): light and dark wordmark, standalone icon.
- Repository layout: `backend/`, `frontend/`, `plugins/`.
- Draft `docker-compose.yml` with infrastructure services (PostgreSQL, Qdrant, MinIO, Redis) and `.env.example`.
- Draft `INSTALL.md`.
- `CLAUDE.md` with project conventions for development sessions.

### Changed
- Design: MVP scope extended with first-run setup, SMTP invites, answer feedback, LLM usage per tenant, single Logs section with syslog forwarding, backup/restore, configuration import/export.
- Design: suggested follow-up questions under each answer.
