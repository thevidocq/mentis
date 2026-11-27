# Changelog

All notable changes to this project are documented here. Every commit updates this file so that work can be resumed from any session.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Fixed
- **Answers cut silently.** An answer longer than the provider's token limit was saved cut mid-sentence. The default limit is now 4,000 tokens (was 1,500; reasoning models count their thinking in it) and a cut answer ends with a note saying so (added after the check, like the record links).
- **Answer check noise.** List items without a citation take the citations of their heading, parent item or lead line ("If it is a true positive [2]") and are verified against them; a line heading nested items is an introduction. The answer prompt asks to cite a list's heading when all items share its passages and no longer to write sentences about where the passages come from (the source is already shown above the answer): these sentences were flagged as uncited and rejected by level 2. Statements without a citation are one line under the answer however many (each wrong value and each rejected statement keeps its own line, same style as before); the per-line **Open source ›** links are gone (the Sources button is right above). An answer from the General Knowledge Base is not shown as a problem. Help (analyst chat, AI providers), DESIGN; tests.

## [0.5.0] - 2026-11-27

### Added
- **Markdown and JSON uploads.** `.md` / `.markdown` (one section per top-level heading, headings in code blocks ignored; UTF-8) and `.json` (valid UTF-8 JSON). A Mentis JSON export (`mentis-document/1`) is read back with its own pages, so documentation moves between customers or installations without loss; any other JSON becomes readable Markdown (one section per top-level key or item, nested lists, arrays of flat records as tables). Validated at upload (UTF-8, no binary content, JSON parses, depth); parsed by the standard parser also when Docling is on. Upload hints, overview colours, help, README, DESIGN; tests (`test_documents.py`).
- **CSV, TSV, YAML and picture uploads.** CSV/TSV (`app/ingestion/datafiles.py`) become one table like an Excel sheet (delimiter detected: comma, semicolon, pipe, tab; 5,000-row limit). YAML (`.yaml`/`.yml`) is one section per YAML document, labelled by `title`/`name`/`id`, text kept as written: composed, never constructed, so no Python tags run and anchors/aliases are never expanded (alias bombs stay small), at most 200,000 values. PNG/JPEG (`.jpg`/`.jpeg`, `app/ingestion/images.py`) are read with OCR (EXIF orientation, transparency on white), the picture kept as WebP preview; refused above 50 million pixels, checked from the header at upload and again in the worker. Docling, when on, now applies to PDF and Office files only. New dependency `pyyaml` (already present through `uvicorn[standard]`, now explicit). Help, README, DESIGN; tests.

### Fixed
- Upload review (Markdown, JSON, CSV, YAML, pictures): YAML values are counted from libyaml parser events before any tree is built (a large YAML file stalled the API for minutes), and upload checks run off the event loop. CSV/TSV with more than 500 columns are refused (one very wide row exhausted the worker's memory); TSV is read without quoting (a cell starting with `"` swallowed the rest of the file); a CSV without a consistent delimiter is read as one column of lines instead of a ragged table. Phone JPEGs with a multi-picture header (MPO) are read; damaged pictures fail with a clear message. Markdown code fences follow CommonMark (inline ```` ``` ```` spans and longer fences no longer hide or invent sections; `# C#` keeps its name). YAML keeps comments with their document, uses a fence longer than any backticks inside, and multi-line titles become one-line labels. Chunks keep fenced code blocks whole or split them by lines with the fence repeated, and `#` lines inside code are no longer headings; the hard cut of very long lines is linear. A Mentis JSON export keeps OCR, confidence, tables and flags when imported, with a warning when pages are left out. Empty files (blank text, `{}`/`[]` JSON, comment-only YAML, empty CSV) are refused at upload. Rename accepts `.yml`↔`.yaml`, `.jpeg`↔`.jpg`, `.markdown`↔`.md`; the originals ZIP keeps the uploaded extension, and exports strip only the extension of an accepted type (`.markdown` included; customer names with a dot such as "Contoso.Holding" are no longer cut in ZIP names); downloads of originals keep non-ASCII names; **New version** offers only files of the document's type. Help, DESIGN, INSTALL updated.

## [0.4.1] - 2026-11-27

### Security
Fixes from the v0.4.0 vulnerability assessment ([docs/security/va-pt-v0.4.0.md](docs/security/va-pt-v0.4.0.md)).
- **Answer check could say "Matches the sources" for statements it never checked** (High, C-1): substantive statements without a citation are now level-1 issues (*"cites no source"*); a statement's values must be in the passages **it** cites, not in any passage (C-2); phone numbers no longer match when truncated.
- **Credentials bound to the account, not only the address** (High, B-1): changing a field that decides whose data the credentials open (Defender/Entra tenant ID, client IDs, CrowdStrike child CID and cloud, Jira account, deployment and projects, ServiceNow user, Vision One region; `"identity": true` in plugin schemas) requires the credentials again, also on configuration import.
- **SSRF through integration addresses** (Medium, A-1/E-1/A-4/A-6): HTTPS only; addresses without user name, `?`, `#` or `\\`; destinations resolved once and pinned; loopback, link-local (cloud metadata), reserved and Mentis' own services always refused; private networks and plain HTTP only with the new super-admin setting **Private network addresses** (`GET/PUT /platform/integrations/settings`); proxies from the environment ignored.
- **Slow or hostile servers** (Medium, A-3/D-1): 30 s total per plugin call (not only per read), at most 6 plugin calls at once per API process.
- **Decompression bomb** (Medium, A-2): answers inflated in bounded steps, the 2 MB cap holds after decompression.
- **Exports** (Medium, D-2/D-3/E-6): the ZIP cap applies to Markdown and JSON too; one ZIP prepared at a time (429 otherwise); nginx streams downloads without buffering.
- **Prompt injection** (Medium, C-3/C-4): passage text folded (NFKC) and opening and closing passage tags neutralised in the answer prompt and in the checker prompt; the checker is told that instructions in passages are a reason to judge strictly.
- Per-user rate limits (D-4): chat 30/min, Test / Try a lookup 20/min, exports 10/min (`MENTIS_*_RATE_PER_MINUTE`).
- Function calling chosen by a tenant admin lapses when the customer goes back to the platform LLM or tenant admins may no longer choose it (B-2).
- Disabled customer: no Test or Try a lookup (B-6); `#` changes refused on a chat whose customer is no longer available (B-5).
- Status page: Jira test detail no longer shows the account name (B-4).
- Links: addresses in brackets, `www.` and `//host` forms are removed too when not in the sources (C-5); a hidden draft no longer names the chat (C-6); backslashes refused in record links (A-7).
- Secrets: `MENTIS_SECRET_KEY_PREVIOUS` for key rotation; a secret that cannot be decrypted is logged (E-3).
- Build and plugins (E-4/E-5/E-8): plugins installed with a pinned build backend, no build isolation, from a bind mount, before the app code; only `mentis-*` packages register connectors, duplicate names refused.
- Authorization matrix: the new settings route, and the integration secret is a forbidden token in every response (B-7).
- Docs: security report, INSTALL (destinations, metadata firewall rule, limits, key rotation), help (answer check, private addresses, credentials and accounts, exports), DESIGN; release note with rollback.

### Added
- **Integration lookups: Standard or Function calling**, per customer (Settings → Integrations for tenant admins; Tenants → LLM for super-admins). *Standard* (default) is the existing mode. *Function calling* lets the model read each result and ask for further lookups (ticket → host → alerts), up to 3 steps and 8 lookups per question, with native tool calling for Anthropic, OpenAI Chat and the Responses API (`services/llm/tools.py`, `services/integrations/tool_loop.py`). Same guards: the chat's integrations only, declared read operations, argument patterns, read-only HTTP client, audit. A model or provider without function calling falls back to Standard without reading twice (`integration.tools_unavailable`). Tenant admins change it only when the customer uses its own LLM chosen by them; `GET/PUT /tenants/{id}/integration-mode` (authorization matrix), `tenant.integration_mode` in the logs, `integration.planned` carries the mode and rounds; exported and imported with the configuration (`integration_mode`).
### Changed
- Answer check shown as it really runs: with no checker configured, the chat says **self-checked by <model>** (the model that wrote the answer re-read it) instead of "checked by"; the customer's LLM page (read-only view) names the model that actually checks (*None set: the model that writes the answer checks it (…)*, the customer's LLM, or the platform checker) instead of a generic "Platform default"; AI providers shows "No checker" as a warning recommending a different model for an independent check. Help updated.
- Help: *Customer settings* explains both modes (strengths, requirements, cost, the accepted risk, who chooses, recommendation); super-admin help updated.

## [0.4.0] - 2026-11-26

### Added
- **Integrations (`#`)**, read only: in a chat on one customer, `#` (or the Integrations chip) chooses the customer's integrations; Mentis reads tickets, devices and alerts at the moment of the question and cites them like documents (one numbering, Sources panel marked *live*, answer check on them too).
  - Identifiers with an unmistakable shape (INC0012345, SOC-123, alert ids) are looked up directly; a short planning call to the chat's LLM adds lookups for host names, IPs and searches (max 4 per question; its own row in LLM usage, *<model> · integration lookups*, event `integration.planned`). Works with every provider, no native tool calling.
  - **Links to what was found**: the model writes a record's id as a link to its page (ticket, device, alert, IP page in Defender); a cited record the answer does not link gets an **Open:** line under the answer; the Sources panel has **Open in <product>** and the extra links. Only links of the records found stay links. An address written in a passage (e.g. a portal in a procedure) stays as plain text; any other address (invented by the model or planted in a ticket) is removed. Checked in the API and again in the browser.
  - Lookups that fail or find nothing are named in a short line under the answer; the cause goes to the Logs only.
- **Plugins** (`plugins/<name>/`, entry point `mentis.connectors`, standard library only, installed into the api image): **ServiceNow** (ticket by number incl. SIR/CHG/PRB/RITM/SCTASK, search, open tickets of a host; basic, OAuth client credentials or API key; extra fields), **Jira** Cloud and Data Center (issue by key, JQL search, open issues of a host; projects limit; extra fields), **CrowdStrike Falcon** (host and containment, alerts of a host, alert by composite id, open alerts; regions; MSSP child CID), **Microsoft Defender for Endpoint** (device with IP links, alerts of a device, alert by id with evidence and incident link, open alerts, IP statistics; regional APIs), **Trend Vision One** (endpoint, Workbench alerts of an endpoint, alert by WB id, open alerts; regions), **Microsoft Entra ID** (new type *identity*, record kind *user*: user with account state, MFA methods, risk, last sign-in; recent sign-ins of a user; users at risk; Microsoft Graph, parts needing a missing permission or P1/P2 licence left out). Tests: `python -m pytest plugins/` (fake HTTP, no services).
- **Core connector runtime** (`app/connectors/`): contract, plugin registry, HTTP client that allows only GET plus declared read POSTs (token, alert queries), only to the instance's origins, without redirects, with time, request and size caps; records capped and cleaned (links must be http(s) without Markdown-breaking characters).
- **Platform → Integrations** (super-admin): enable the installed types; counts of customer integrations. `GET/PUT /platform/integrations`.
- **Tenant → Integrations** (tenant admin): add (form generated from the plugin's schema), edit, **Test**, **Try a lookup**, turn off, delete. Credentials encrypted and write-only; sent only to the origin they were saved for (changing the address requires them again). `/tenants/{id}/integrations[/{iid}[/test|/run]]`. The General Knowledge Base has no integrations.
- Chat API: `GET /chats/integrations?tenant_id=`, `integration_ids` on `POST /chats` and `PATCH /chats/{id}` (validated against the chat's own customer; 422 otherwise), on chat summaries; citations of live records carry `kind: "integration"`, product, integration, record, `url`, `links`.
- Service status: one line per active integration (category Integrations), tested in parallel with a 5 s timeout. Logs: `integration.called` (integration, operation, object ids only, ok/cause, latency), `integration.created/updated/deleted/tested`, `chat.integrations`, `platform.integrations`.
- Configuration export/import: enabled types and each customer's integrations **without credentials**; imported integrations are added turned off; one whose address changes loses its stored credentials.
- **Documents: download formats.** The download button of a document (and of each version) is a menu: **Original**, **Markdown** (the text read, page by page, with customer, version, file, date and SHA-256) and **JSON** (`mentis-document/1`: metadata, pages, indexed passages with page and section, to import elsewhere). **All** at the top of the list downloads every document in use as a ZIP in one of the three formats, with `manifest.json` (files, versions, how many were left out). ZIP of originals limited by `MENTIS_EXPORT_MAX_MB` (300). `GET /tenants/{id}/documents/export?format=` and `/versions/{vid}/export?format=md|json`; audited `documents.exported`, `document.exported`; in the authorization matrix.
- Help: *Integrations* (tenant admin) has **Minimum requirements** per product: credentials, read-only permissions, licences and the addresses Mentis must reach (how to create the credentials stays in each product's documentation). Logs lists the new events; Documents explains the download formats and **All**; *Integrations* for super-admins and tenant admins; analyst chat help (`#`, links). Authorization matrix extended (plugins, instances under every tenant id, chat integrations); `tests/test_integrations.py`.

### Changed
- Prompt: live records are labelled "read now from <integration>", treated as data, and their ids written as links to the given page.
- Deleting a tenant deletes its integrations and their credentials.
- Docker Compose 2.17 or later (second build context `plugins` for the api image).

Migration 0013 (`integrations`, `chats.integration_ids`).

## [0.3.7] - 2026-11-26

### Fixed
- Storage sweep: files of a document uploaded while the sweep ran could be removed as leftovers; storage is now listed before the database rows are read (READ COMMITTED snapshot per query). Test reproduces the race.
- Answer check, Hide mode: a failure while rewriting a wrong answer showed it unchecked; it now stays hidden.
- Answer check: any unexpected error in level 1 or 2 (or around them in the chat route) gives `level2: unavailable` and never breaks the answer.
- Level 1: year ranges, ISO dates (now dates), number ranges and amounts with thousands separators are no longer phone numbers.
- `history_note` is empty for hidden answers.
- Chat: unexpected answer-check errors no longer give a 500 (undefined logger); grouped citations `[1, 2]` are recognised; customer names with quotes no longer break the passage tags; `"not_found": "false"` from weak models is read as false; NUL characters in questions and replies are removed (PostgreSQL refuses them).
- Auth: password-reset and invitation links are single-use under parallel submits (the second gets 404, no 500); without SMTP, "Forgot password" no longer invalidates a link an admin created by hand.
- Documents: approve/restore with Qdrant down answers 503 and changes nothing; a duplicate ingest job no longer re-processes a ready version (approval reset, version out of answers); Qdrant/MinIO internals no longer appear in version errors shown to tenant admins; downloads answer 503 when MinIO is down; renaming to the bare extension is refused.
- Platform: a malformed provider address is an LLM error (failover, status page) instead of a 500; an API key echoed by a provider is redacted in the model-list error; config import keeps one default per role, and importing exports older than 0.3.6 no longer resets tenants' checker and answer-check mode; tenant names made of spaces are refused.
- Ops: `backup.sh` free-space check now measures the previous backup (it never fired); it refuses a non-empty existing destination (a failed backup deleted the folder); Postgres healthcheck and `restore.sh` wait over TCP (first start could report ready too early).
- Frontend: late responses no longer overwrite newer ones (chat search, document versions, overview, LLM usage); double clicks no longer send twice (document actions, Add provider); load errors are shown (SMTP, Embedding, Retention, Syslog); the share dialog closes when the chat changes; Escape in a dialog no longer closes the sources panel; mobile drawers close on every navigation; documents on phones with a stale `?doc=`; Retention "Custom…" days while typing; Help on phones has the menu bar.
- Chat polling of a pending check: 90 × 1.5 s, longer than the 120 s after which the server reports it unavailable (was 60 s: "Checking…" could stay forever).

## [0.3.6] - 2026-11-26

### Added
- **Answer check, against hallucinations.** Level 1 (always on, no model): phone numbers, e-mails, IPs, times, durations, percentages, dates and codes in the answer must be in the passages (normalised: "085 1112233" = "+39 085 111 2233", "30 minuti" = "30 minutes"); answers without citations are flagged. Level 2: a checker model verifies each cited statement against its passages (general LLMs with JSON verdicts; MiniCheck-style fact-checkers recognised by name). Per customer (LLM page): **Show a warning** (default), **Hide the answer** (one rewrite, then "Not found"; hidden text kept for audit only), or level 1 only.
- Chat: the wrong value or statement is highlighted and a quiet line under the answer says which level found it (Level 1, Level 2, Level 1 + 2), with **Open source ›**; "Matches the sources", "Checking…", "Check not available". Same in shared chats. Flagged answers go back to the LLM as history with a note, so the error does not spread.
- **AI providers**: sections **Answers** and **Answer check**; **Use for** in Add provider (technical fields under **Advanced**); one default per section, **Set as default** on the row (adding a model never changes it); **Test** of a checker plants an error and checks it is caught. Per customer: a specific checker (a customer with its own LLM is checked by that LLM unless one is chosen).
- Logs: `chat.checked` (mode, level, issues, model, tokens). LLM usage: rows "<checker> · answer check".

### Changed
- Answers are generated with **temperature 0**; models that refuse the parameter are asked again without it.

Migration 0012 (`llm_providers.role`, `chat_messages.answer_check`).


## [0.3.5] - 2026-11-26

### Changed
- **Documents as a document browser**: the list on the left (search, All / In use / To review, documents needing attention grouped first with a quiet badge) and the selected document on the right: state, Approve/Reject or Retry when needed, **New version**, Download, a ⋯ menu (Rename, Versions, Delete), and the tabs Preview, Text read, Versions, Test a question; details and recent versions on the right on wide screens. On a phone: list, then the document with a back button.
- **Documents overview** when the page opens (instead of the first document): documents in use, pages read and OCR, passages searchable, questions in chats on the customer in the last 30 days, what needs attention with Retry / Review, content by type, last indexed, oldest in use, pages to check, recent activity (`GET /tenants/{id}/documents/overview`, in the authorization matrix).
- **Chat answers** sit in a light frame (hairline fading from the top-left corner, faint teal trail, very light shadow); the customer is a small text line, no longer a rounded badge, also in the chat header. Lighter citation numbers and follow-up chips; the Sources line under the answer is now a small button (only as wide as its text) that opens the panel on the right.

### Added
- **New version** of a document accepts any file name of the same type (`document_id` on upload).
- `MENTIS_EMBEDDING_BATCH_SIZE` in `.env` now reaches api and worker (texts per request to the embedding service; 4 on hosts with little RAM). INSTALL: plan at least 8 GB RAM, or add swap.

### Storage (long-term)
- **Container logs rotated** (5 × 20 MB per container; `MENTIS_LOG_MAX_SIZE`, `MENTIS_LOG_MAX_FILES`): the default Docker driver grew without limit and could fill the disk.
- **Deleting a document** removes its rows first and then files and vectors: before, a MinIO or Qdrant outage half-way left a document that was still listed but no longer searchable.
- **Daily storage sweep** (with the retention purge): removes files and index entries that no row refers to (deletions while MinIO or Qdrant were down, deleted tenants). Deleting a tenant cleans files and index after the commit.
- **Old document versions** (Retention, default keep all): keep the last 1, 3, 5 or 10 older versions per document; the version in use, the latest and pending ones are always kept. Included in configuration export/import.
- **Page images in WebP** (about a quarter of a PNG); existing PNG images keep working.
- **Qdrant vectors on disk** (memory-mapped) for new collections; existing ones are moved by the sweep. RAM no longer grows with the number of documents.
- MinIO deletions in batches of 1,000 (was one request per file).
- `backup.sh`: keeps the newest 7 complete backups (`MENTIS_BACKUP_KEEP`), checks free space first, removes a backup that failed half-way.
- `check.sh`: Storage section (free disk, volume sizes, backups, reclaimable images and build cache, log rotation). INSTALL: "Storage over time" and image prune after upgrades.

### Fixed
- On a phone the menu did not close after choosing a customer on the same page.
- `backup.sh` failed with "No such image" when the api image id of the container it used no longer existed (after rebuilds): it now uses the running container and the image by name (`mentis-api`). Same for `restore.sh`.

## [0.3.4] - 2026-11-26

### Added
- **Share a chat by link**: **Share** in the chat header creates a read-only link for colleagues signed in to Mentis who see the chat's customer (for an "All customers" chat: every customer of the owner). Answers that used a customer the viewer does not see are left out with their question; the owner's ratings are not shown. One link per chat (a new one revokes the old), only its hash is stored, expiry 30 days (`MENTIS_CHAT_SHARE_DAYS`), revoked when the chat is deleted or the owner disabled. Audited: `chat.shared`, `chat.share_revoked`, `chat.share_viewed`, `chat.share_denied`. Migration 0011 (`chat_shares`). Authorization matrix and tests extended.
- **Sources panel on the right**, like other AI chats: the Sources bar and every [n] open the cited documentation beside the chat instead of under the answer (full screen on a phone; Esc or × closes it).

### Changed
- Wider side menu (320 px); the brand row and the page/chat header have the same height, so their bottom lines are aligned.
- Admin sidebar: the context block reads **Tenant** (was Customer), with more space around the label and the tenant switcher.

### Fixed
- `check.sh` reported "`.env` still contains CHANGE_ME placeholders" because of the comment at the top of `.env.example`: comment lines are now ignored.

## [0.3.3] - 2026-11-26

### Changed
- Desktop layout: pages are centered next to the menu (readable width: 1200 px, 860 px for forms and settings, 1560 px for Logs), and the side menu is wider (280 px).

## [0.3.2] - 2026-11-26

Security release: authorization matrix over every API route, penetration test (report in `docs/security/pentest-v0.3.2.md`), infrastructure hardening, frontend review.

### Changed
- **Desktop layout like Equalizer**: page title and content keep a readable width (1200 px, Logs 1560 px) aligned left, instead of stretching across wide monitors; the page header is part of the page, not a full-width bar.
- **General Knowledge Base** (was "General"): general knowledge only (threat-handling procedures, playbooks, best practices), never customer context; a banner on its Documents page says so.
  - Everyone reads it in the chat, no tick needed. For tenant admins the tick now means **Can manage the General Knowledge Base**: off by default, not implied by "All customers", granted only by those who have it.
  - Every new version needs approval before it is used (it reaches every customer).
  - In the chat the **Knowledge Base** chip is on by default next to the customer; turning it off for a chat is explicit, with a confirmation, and logged (`chat.general_knowledge`).
  - Migration 0010: renames the tenant, removes the now meaningless ticks of analysts, adds `chats.use_general`. Tenant admins who had General keep the management permission: review them in Users.

### Security
- API answers (documents, page images, originals, chats, logs, errors) are sent with `Cache-Control: no-store`: the browser no longer keeps tenant data on disk, e.g. page images were cached for an hour on shared PCs.
- The tenant admin's current and recent customers are stored per user in the browser: on a shared PC the next user no longer starts on (or sees the order of) the previous user's customers; the old shared keys are removed.
- Back to a Mentis tab, the app re-reads who is signed in: customers granted or removed show at once, and if another user signed in from another tab the page reloads, so no chats or customer ids of the previous user stay on screen or are used.
- After sign-in, only a path of this app is used as the return address (no `//host` redirect).
- Network segmentation: PostgreSQL, Qdrant, MinIO, Redis and embeddings moved to an internal network (`mentis_data`) shared only with api and worker; the web container (and any network it joins, e.g. `equalizer_edge`) can no longer reach the data stores.
- API refuses to start in production with the built-in `dev-only-change-me` secret key or any `CHANGE_ME` placeholder secret (`MENTIS_ENV=development`/`test` allows the dev key); compose stops if a required secret is empty, so Qdrant can no longer start without an API key.
- Containers hardened: `no-new-privileges` and `cap_drop: ALL` everywhere (data stores keep only the capabilities their entrypoint needs); web, api and worker run non-root on a read-only root filesystem with `/tmp` in tmpfs; memory/PID limits on web, api, worker, redis; healthchecks for web, qdrant, redis.
- Web image moved from `nginx:1.27-alpine` (end of life, open nginx CVEs incl. resolver use-after-free) to `nginxinc/nginx-unprivileged:1.30-alpine` (runs as uid 101).
- Image tags pinned: `qdrant/qdrant:v1.20.0` (was `latest`), `redis:7.4` (was `7`); Qdrant telemetry off; MinIO web console disabled.
- Request bodies limited to 10 MB at the web proxy (100 MB only for document uploads); client body/header timeouts set.
- Python dependency floors raised to pip-audit-clean versions (cryptography 50, python-multipart 0.0.31, Pillow 13, starlette 1.3.1, urllib3 2.8, h11 0.16, anyio, idna, certifi, protobuf, lxml, pdfminer.six); the change also refreshes the cached dependency layer of the Docker build.
- `backup.sh` writes every file owner-only (`umask 077`) and can encrypt the backup with gpg (`MENTIS_BACKUP_GPG_RECIPIENT` or `MENTIS_BACKUP_PASSPHRASE_FILE`); `restore.sh` restores `.tar.gpg` backups.
- `check.sh` reports `.env` permissions, leftover `CHANGE_ME` placeholders, and data services attached to other networks or publishing ports.
- INSTALL: `chmod 600 .env` right after creating it; note on narrowing `MENTIS_TRUSTED_PROXIES` when users connect from a private LAN without a proxy.
- Chat history: answers that used a customer no longer assigned to the user (removed from the account) are hidden, with their sources and follow-ups, also in the feedback response, and are no longer sent to the LLM as history of "All my customers" chats; citations now carry the tenant id (older ones are matched by name, unknown = hidden).
- Service errors shown to analysts and tenant admins (chat answer, "Test a question", failed version) no longer include internal addresses or raw provider/embedding replies; the cause stays in the Logs (`document.failed` gains `cause`, new `document.test_question_failed`).
- Tests: authorization matrix (`backend/tests/test_authz_matrix.py`) over every API route, nine actors and objects of other tenants (IDOR), with leak checks on every response; a new route without an expectation fails the test.
- PT-01: sign-in, 2FA, password reset, invitation and setup requests are rate limited per client IP (`MENTIS_AUTH_RATE_PER_MINUTE`, default 30/min, 429 above): no unlimited password spraying, no Argon2 CPU exhaustion from one client.
- PT-02: "Forgot password?" does the lookup and sends the email after answering, so the response time no longer reveals which emails have an account.
- PT-03: a stored AI provider API key is only sent to the origin it was saved for: model listing with another address, editing the address without re-entering the key (422) and a configuration import that moves a provider (key dropped) can no longer send it elsewhere.
- PT-04: PDF pages and pictures are rendered/OCR'd within a 40-million-pixel budget: a tiny PDF declaring a huge page no longer takes gigabytes of worker memory.
- PT-05: chat answers that fail show a generic message to analysts; provider/embedding error bodies and internal addresses go to the logs only.
- PT-06: malformed requests (NUL characters, lone surrogates, deeply nested JSON) get 4xx instead of 500, and validation errors no longer echo the submitted values (e.g. a password).
- PT-08: upload checks: macro parts and content types are matched case-insensitively; control and bidi format characters (U+202E) are removed from file names.
- PT-09: a passage closing tag is neutralised in any case or spacing, so a document cannot end its own passage in the prompt.
- A stored AI provider API key is never sent to another address (model listing or a URL change requires the key again).
- Chat search no longer matches words inside answers hidden after an access change.

### Fixed
- Chat: an answer arriving after switching to another chat was appended to that chat (and the next question went to the first one); a slow chat load could replace the chat just opened. The composer waits for the chat to load.
- Answers, extracted text or passages containing a line like `#tag` or `| a` froze the browser tab (endless loop in the Markdown renderer); a table of separator rows only crashed the page.
- Documents: overlapping polls on slow networks could overwrite newer data and reopen version lists just collapsed; polling now waits for each answer. Opening versions reports errors instead of failing silently; the same file can be chosen again for upload.
- Logs: a slower answer for older filters no longer replaces the results of the newer search.
- Chat rename and delete show the server's error in the dialog instead of failing silently; failed clipboard copies no longer raise unhandled errors.
- Configuration import: a lost session signs out and validation errors read as text (was "[object Object]").
- Dialogs keep keyboard focus inside and return it to the control that opened them; the customer selector closes on Tab, returns focus on Escape, announces the highlighted customer and keeps it in view.
- Documents: the "uploaded, processing" notice now goes away when the document is ready or failed.
- Invitations: General is ticked by default even when the customer list arrives after the form opened.
- Embedding requests send 16 texts at a time (was 32), using less memory on small servers.

## [0.3.1] - 2026-11-26

### Added
- **Models listed by the provider**: in AI providers, **Load models** asks the provider (`GET /models`: Anthropic, OpenAI, Ollama, vLLM) which models it offers and lets you pick one from a list, newest first; **Other** allows typing a name. Presets no longer carry model names (no Claude Haiku or other fixed model).
- **Forgot password?** on the sign-in page: a one-time link by email (60 minutes). Admins can create a 24-hour reset link from **Users** (envelope icon), emailed or shown to copy when SMTP is off. 2FA stays required, every session is closed, the account is unlocked; migration 0009 (`password_resets`).
- **Customer selector with search**: the tenant area switcher opens a panel with **Search customers…**, General first, then the last customers used; the customer list in invitations and user edit gets a search box and **Selected only** when there are many customers.

### Changed
- **Sources under an answer are compact**: one closed line with the number of documents and sections, one block per document, sections in number order, customer badge only when the answer mixes customers or uses General.
- **Chat header**: logo on its own row; search box with a **+** button for a new chat.
- **Account** opens inside the usual menu (with Log out at the bottom); the separate header with Back and Sign out is gone; themes are three compact tiles also on a phone.
- Passwords are limited to 256 characters (bounds the hashing work of a request).
- **Docker builds reuse their cache across releases**: system packages (Tesseract) and Python dependencies are installed from a list extracted from `pyproject.toml` before the app code is copied, and `npm ci` runs on `package.json`/`package-lock.json` with the version blanked; a version bump or a code change no longer reinstalls them (the first build after this change still installs everything once).

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
