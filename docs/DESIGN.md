# Mentis – Project Design Document

_Last updated: 2026-11-26. Living version: the shared design doc; this file is the repo copy._

## Overview

Mentis is a standalone, multi-tenant web app: an AI assistant that answers SOC analysts from each customer's own documentation, with sources cited on every answer.

- **Problem:** a SOC serving many customers has procedures, escalation matrices and runbooks spread across PDF, Word, Excel and PowerPoint (and Markdown, JSON, CSV, YAML or screenshots from wikis and tools), different for every customer.
- **Answer:** one RAG index per customer tenant, plus a shared General Knowledge Base, queried through a chat interface.
- **Principle:** analysts consult only. Mentis never writes to customer systems.
- **Positioning:** the core is domain-agnostic; SOC is the first vertical pack (labels, integration catalog, system prompt). Anything SOC-specific lives in configuration or plugins, not in the core.
- **Style:** modular code, Docker Compose first, Kubernetes later, React frontend.

## Users and roles

| Role | Area | Can do |
| --- | --- | --- |
| Super-admin | Platform admin | Onboard, edit and delete tenants; users; configure AI providers, embeddings, retention; enable integration types and private addresses (customer integration options only through the configuration export, never credentials); decide per tenant whether its admins choose the LLM; view service status and audit log. **No chat, no documents** |
| Tenant admin | Tenant admin + chat | For each of its customers: upload, version, preview and approve documents (the General Knowledge Base too, only with the explicit permission); choose tenant LLM when allowed; configure integrations; invite and manage tenant admins and analysts within its customers; chat |
| Analyst | Chat + account | Chat (read-only consultation) on its customers, own profile, theme, password |

- Tenant admins and analysts have **assigned customers** (`user_tenants`), or `all_tenants` = every customer including future ones. Everyone reads the General Knowledge Base; for a tenant admin, ticking it means "can manage the General Knowledge Base" (off by default, not implied by `all_tenants`, granted only by those who have it). The rules live in `backend/app/services/access.py` and are re-checked on every request and every question.
- A tenant admin grants only customers it has (all only with `all_tenants`), sees only users whose customers are all its own, and cannot change its own role or customers. Changing a user's customers revokes its sessions. Saved answers that used a customer the user no longer has are hidden (answer, sources, follow-ups) and never sent back to the LLM as history.
- Tenant admins see AI providers as name + model only and usage without costs.
- In the tenant area a selector picks the customer the pages show; in the chat `@` lists only the user's customers plus "All my customers".
- The first super-admin is created on the server (`app.cli create-admin`); the browser setup page is off by default.
- Every user has an account page: profile, theme (Light / Medium / Dark), password change, 2FA status.

## Tenancy model

- **Customer tenant:** own documents, vector collection, LLM settings, integrations, users.
- **General Knowledge Base:** flag `global`, exactly one, named "General Knowledge Base". General knowledge only (threat-handling procedures, playbooks, best practices), never customer context. Read by every tenant admin and analyst; managed only by tenant admins with the explicit permission (every action logged); every version needs approval. Cannot be deleted.
- **Precedence:** when the General Knowledge Base and customer documents disagree (escalation, SLA), the customer document wins; the answer may flag the conflict.
- **Opt-out:** per-tenant setting "Include the General Knowledge Base", default on; per chat, the analyst can turn it off explicitly (the "Knowledge Base" chip, on by default, with a confirmation; `chats.use_general`).
- **Isolation:** the tenant filter is applied server-side on every query, never left to the prompt or the frontend.
- **Deletion:** removes documents and versions, Qdrant collection, chats, LLM and integration settings; its tenant admins lose it, and those left without a customer are deleted. Audit log is kept per retention. Confirmation requires typing the tenant name.

## Chat experience

One chat = one customer scope, locked at the first message; integrations (`#`) are chosen per chat and can change between questions.

**Layout**

- Left sidebar, clearly separated blocks: logo + "New chat" (light outlined button), history search, history grouped by day, account link at the bottom.
- History items show title and `@customer`; the active chat has rename and delete icons.
- Header: chat title and customer badge (lock icon once locked). The LLM that wrote each answer is shown under it, with latency.
- **Answer check** (`services/answer_check/`): level 1 compares critical values (phones, e-mails, IPs, times, durations, percentages, dates, codes; normalised) with the passages given to the model, and flags answers without citations; level 2 asks a checker model (role `checker` in AI providers; per customer: chosen checker > the customer's own LLM > default checker > the answering model) whether each cited statement is supported (JSON verdicts; "Document/Claim -> Yes/No" for MiniCheck-style models). Level 2 runs in groups of 10 statements (≤ 24 in all), each call limited by the customer's `check_max_tokens` (500–16000, default 2500, **LLM** page, tenant admin even when models are locked); an empty or unreadable reply is retried once; failures are logged with the provider's stop reason (`LLMReply.stop`: end_turn, max_tokens, refusal, length…), tokens used and the limit, and so are answers cut by Max answer tokens. Modes per tenant: warn (default; level 2 after the response, the browser polls), hide (both before the response; one rewrite with the problems, then "Not found", hidden text kept for audit only), off (level 1 only). Results on `chat_messages.answer_check`; issues carry the level(s) that found them, shown to analysts as Level 1 / Level 2 / Level 1 + 2. Flagged answers go back to the LLM as history with a note. Logged as `chat.checked`; costs in usage as "<checker> · answer check". Answers and checks use temperature 0 (retried without it when a model refuses the parameter).
- Chats are private to their user. Analysts and tenant admins chat on their own customers; super-admins have no chat.
- **Sharing by link** (owner only): read-only, for signed-in tenant admins and analysts who see the chat's customer (for an "All customers" chat, every customer of the owner, since an answer can draw on passages it does not cite). Answers citing a customer the viewer does not see are left out with their question; the owner's ratings are not shown. One active link per chat: a new one revokes the old; only its hash is stored; it expires after `MENTIS_CHAT_SHARE_DAYS` (30), with the chat, or when the owner is disabled. Created, revoked, viewed and denied views are audited (`chat.shared`, `chat.share_revoked`, `chat.share_viewed`, `chat.share_denied`).

**`@` customer scope**

- `@` opens the user's customer list: "All my customers" / "All customers" (default, when there is more than one), each assigned active customer, then "General Knowledge Base" (the knowledge base alone).
- The scope is fixed by the first message. Afterwards `@` shows the list greyed out with "Customer locked for this chat" and a link to start a new chat.
- A chat started on "All customers" stays on "All customers".
- The backend uses only the tenant stored on the chat, whatever the frontend sends.

**`#` integrations**

- `#` (or the Integrations chip under the input) lists the chat's customer's usable integrations (enabled instance, plugin installed and enabled by the super-admin) with product and type; multi-select.
- The choice is stored on the chat (`chats.integration_ids`) and applies to the next questions; it can change at any time (`PATCH /chats/{id}`, audited `chat.integrations`). The server re-checks every id against the chat's own customer on every question; ids of another customer are refused (422) and removed or disabled instances are ignored.
- No `#` = documentation only. In "All customers" chats and on the General Knowledge Base alone `#` is disabled.

**Answers**

- Every answer states which customer it refers to (and "+ General Knowledge Base" when used).
- Citations: one numbering for documents and live records, [1], [2]. Documents carry document, version, page/sheet/slide; live records (`kind: "integration"`) carry product, integration, record id and kind, and the record's links (`url`, `links`: e.g. the device or IP page).
- **Links to live records**: the prompt asks the model to write a record's id as a link to the "Link" given in its passage; links that do not come from a record found for this question are reduced to their text; addresses written in a passage stay as plain text, any other address is removed, and a cited record the answer does not link gets an "Open: [product kind id](url)" line under the answer (added after the answer check, like the notes on failed lookups). The browser renders `[text](url)` as a link only for URLs of the answer's cited records.
- If the documentation does not cover the question: "Not found in <customer> documentation", never an invented procedure. With no passage above the score threshold the LLM is not called at all; the model can also flag not-found itself.
- Passages go to the LLM as numbered, untrusted data blocks labelled with their customer; citation numbers not among them are dropped.
- Each answer sits in a light frame (hairline fading from the top-left corner, faint teal trail, very light shadow); its customer is a small text line above it, not a badge; the chat header shows the customer as quiet text after the title.
- Sources under the answer are one small button ("Sources · 1 document · 8 sections"). A click opens the **Sources panel on the right** of the chat (full screen on a phone): one block per document (version) with its cited sections in number order. The customer badge appears only when the answer mixes customers or uses General. A click on [n] opens the panel on that section.
- The last turns of the chat are sent as context; short follow-ups also reuse the previous question for retrieval.

**Suggested follow-ups**

- 2–3 clickable chips under each answer, produced by the same LLM call (structured output), no extra request.
- Grounded: only questions the retrieved sources can answer, so a click never lands on "not found".
- A click sends the question as a new message in the same chat and customer scope.
- (Later) a suggestion needing an integration pre-selects its `#` chip, only if that integration is enabled for the customer.
- Per-tenant setting, default on.

**Titles**

- Generated with the first answer, in the same LLM call (4–6 words, no customer name).
- Fallback: first 60 characters of the question. Manual rename locks the title.

## Document ingestion and versioning

Uploads run as background jobs; a new version reaches answers only once indexed (and approved, when approval is on).

**Pipeline**

1. Upload (PDF, DOCX, PPTX, XLSX, Markdown `.md`/`.markdown`, JSON, CSV, TSV, YAML `.yaml`/`.yml`, PNG, JPEG `.jpg`/`.jpeg`; up to 50 MB) → validated (extension matches content; text formats must be UTF-8 and parse (YAML composed only, never constructed, at most 200,000 values); pictures by header, at most 50 million pixels; no macros, no encrypted Office files, zip-bomb guard; a PDF that needs a password to open fails in the worker, one that only restricts printing or copying is read) → original stored in MinIO under a generated key.
2. The ingestion worker (separate container, RQ on Redis, CPU/RAM limits, 30-minute timeout) parses the file into pages:
    - PDF: one page per page; native text and tables via pdfplumber; pages with almost no text are rendered (pypdfium2) and read with Tesseract OCR (English + Italian) with a confidence score; every page is rendered as an image for the preview.
    - DOCX: split into sections at top-level headings; headings and tables preserved.
    - PPTX: one page per slide; title, text, tables, speaker notes, and OCR of pictures (screenshots, diagrams).
    - XLSX: one page per sheet as a Markdown table (values, not formulas); merged title rows become captions.
    - Markdown: one section per top-level heading. JSON: a Mentis export keeps its pages; other JSON is rendered as Markdown.
    - CSV / TSV: one table (delimiter detected: comma, semicolon, pipe, tab; no consistent delimiter → one column of lines; TSV unquoted), same row limit as a sheet, at most 500 columns.
    - YAML: one section per YAML document, labelled by `title`/`name`/`id` (Sigma rules, playbooks), text kept as written in a code block, comments with the document they precede; values counted from parser events (libyaml) before any tree is built, so anchors are never expanded and oversized files stop early.
    - PNG / JPEG: one page read with OCR (upright by EXIF, transparency on white), confidence score, the picture kept as preview.
    - The Docling parser, when on, handles PDF and Office files only; the other formats always use these readers.
3. Quality flags per page: OCR + confidence, low confidence (< 60%), empty, merged cells, truncated.
4. Chunks are built per page (never across pages, so citations stay exact), around 1,500 characters, tables kept whole or split by rows with the header repeated, fenced code blocks kept whole or split by lines with the fence repeated (a `#` line inside code is never a heading), each with its nearest heading.
5. Embedding (OpenAI-compatible endpoint; default local TEI container with bge-m3) and upsert into the tenant's Qdrant collection (`mentis_<tenant>`), payload: tenant, document, version, chunk, active. Indexing is the last step: if it fails, the version fails and the active one stays.
6. Activation, approval and restore update the `active` flag in Qdrant. PostgreSQL is the source of truth: every search hit is re-checked against the database (chunk, tenant, version ready and active), so a stale index can never surface a version not in use.
7. Changing the embedding model requires a full reindex (rebuilt from stored chunks, no re-parsing); uploads are refused until it is done.

**Parser choice (decided):** the default parser is the "standard" stack above, fully tested. Docling is available as an option (`MENTIS_PARSER=docling`, image built with the `docling` extra) but is not verified yet: it needs PyTorch and HuggingFace models that the development environment cannot reach. It becomes the default only after a lab test on real customer documents. Apache Tika stays set aside.

**Known weak spots** (why preview exists): poor-quality scans, diagrams without vision, Excel with merged cells or several tables per sheet, multi-column or shape-heavy slides.

**Preview and approval**

- Side-by-side view: original page on the left (PDF page image or the PNG/JPEG picture; for the other formats a link to the original), extracted text on the right.
- Per-page quality flags: native text vs OCR, OCR confidence, tables found, empty or unreadable pages.
- "Test a question" box scoped to that version (works on pending versions too), showing the passages Mentis would use and their match score.
- Optional per-tenant approval: the new version stays inactive until the admin approves it.

**Versioning**

- Same file name (case-insensitive) = new version; renaming keeps the extension. Only the active version is searchable; older ones stay viewable and can be made active again.
- A failed or rejected version never replaces the active one. An upload whose SHA-256 matches any version of any document of the same customer (all file types; failed and rejected versions excepted) is refused (409) with the document and version it matches (`versions.duplicate_message`) and logged as `document.upload_refused`; other customers are not compared.
- Each version records date, uploader and an optional note.
- Documents can be renamed and deleted (with confirmation). Deletion removes the rows first (answers stop at once), then files and vectors; anything left by an unreachable MinIO or Qdrant is removed by the daily storage sweep (no row = leftover; rows are always written before files and vectors).
- Retention of old versions (super-admin, default all): per document the version in use, the latest and pending ones are always kept; older ones beyond N are deleted with files, pages, passages and vectors.
- Storage: page images WebP; Qdrant vectors on disk (memory-mapped; existing collections moved by the sweep); container logs rotated; backups rotated (`MENTIS_BACKUP_KEEP`).
- **New version** of a selected document accepts any file name of the same type (`document_id` on upload).
- The Documents page is a document browser: the list on the left (search; All / In use / To review; *Needs attention* grouped first), the selected document on the right with Approve/Reject or Retry when needed, New version, Download (menu: Original, Markdown, JSON; also on each version) and a ⋯ menu (Rename, Versions, Delete); **All** above the list downloads every document in use as a ZIP (originals, Markdown or JSON, with `manifest.json`; originals capped by `MENTIS_EXPORT_MAX_MB`). Markdown = the pages read with a header (customer, version, file, date, SHA-256); JSON (`mentis-document/1`) = metadata, pages and indexed passages, to import elsewhere. Audited `document.exported`, `documents.exported`, and the tabs Preview, Text read, Versions, Test a question; details and recent versions in a right column on wide screens. The selection is in the address (`?doc=`); without one the right side shows an **Overview** (`GET /tenants/{id}/documents/overview`, counts only): documents in use, pages read and OCR, passages, embedding model, questions in chats on the customer in 30 days with not-found count (not for the General Knowledge Base), needs-attention list, content by type, last indexed, oldest in use, pages to check, recent uploads and approvals.

## AI layer

LLM is configurable per tenant; the platform default is whichever provider the super-admin marks as default. Embeddings stay local.

| Provider type | Use | Notes |
| --- | --- | --- |
| Anthropic | Claude models | API key |
| OpenAI Chat Completions | OpenAI cloud, vLLM, compatible endpoints | `/v1/chat/completions` |
| OpenAI Responses API | Internal gpt-oss (vLLM) | `/v1/responses`, reasoning auto-on for gpt-oss/o-series, API key optional |
| Ollama | Local models | No key |

- Every provider: test connection, failover to the tenant's fallback provider. One platform default; each tenant can choose its own provider and fallback. API keys encrypted at rest. Models are discovered from the provider (`GET /models`) and picked from a list; presets carry no model names.
- **Embeddings:** local by default (bge-m3, multilingual). Other providers configurable (Ollama, OpenAI-compatible endpoints).
- **Vector DB:** Qdrant only, one collection per tenant.
- **Retrieval:** customer chunks + General Knowledge Base chunks (unless turned off for the customer or the chat), active versions only, score threshold; customer wins on conflict. Passages per answer: the customer's setting `chat_passages` (3–20, tenant admin, **Settings**), else `MENTIS_CHAT_PASSAGES` (8); "All customers" chats use the platform value. Variety (`passage_variety`: off | normal | high, default normal, tenant admin): Maximal Marginal Relevance (`services/diversity.py`, Carbonell & Goldstein 1998) — `limit x 4` candidates (at least 24) per tenant are read with their vectors, then picked one at a time by `lambda * relevance - (1 - lambda) * max similarity to the picked ones` (lambda 0.7 normal, 0.5 high); the kept passages are returned in relevance order. Off = plain top-k. Deterministic, no model call; the database still re-checks every candidate.
- **System prompt:** anti-hallucination rules first; answer only from retrieved sources and integration data; cite everything; per-vertical prompt (SOC default), replaceable. All prompts in English.

## Integrations

All integrations are per tenant and read-only; they are invoked from chat with `#`.

| Type | Products (initial) | Reads |
| --- | --- | --- |
| Ticketing | ServiceNow, Jira Cloud, Jira Data Center | Ticket by ID, search |
| EDR | Microsoft Defender for Endpoint, CrowdStrike, SentinelOne | Device, alerts |
| SIEM | Microsoft Sentinel, Splunk | Incidents, alerts |

- **Configuration (tenant admin):** type, URL, authentication, "Test connection", field mapping (priority, assignment group, category, states).
- **Secrets:** encrypted in the database, never shown again in clear text.
- **Backlog (write actions, not in scope now):** work notes drafted by the bot and confirmed by the analyst, ticket create/update, inbound webhooks.

**Plugin model (implemented in 0.4.0)**

- **Contract** (`backend/app/connectors/contract.py`, standard library only): manifest (name, label, version, type, vendor, vertical, core API `1`), JSON Schema config (admin form generated from it; `secret` fields write-only and encrypted, `showIf`, `enumLabels`), `origins(config)` and `read_posts(config)`, `test_connection`, read-only typed `operations` (parameters with patterns; `match` regexes for identifiers with an unmistakable shape), `run` returning normalized `Record`s (ticket, device, alert, indicator, user: id, title, fields, text, url, extra links).
- **Runtime** (`app/connectors/http.py`, `app/services/integrations/`): plugins get a `Context` (config, decrypted secrets, per-instance state for tokens) and an HTTP client that allows GET plus POST only to declared read URLs, only to the instance's origins, HTTPS only, no redirects, no proxies from the environment; destinations resolved once and pinned (Host header and TLS name kept), loopback / link-local (metadata) / reserved / Mentis' own services always refused, private networks only with the super-admin's *allow_private* setting; 15 s per read and 30 s per call in total, 12 requests, 2 MB per answer after decompression (inflated in bounded steps); at most 6 plugin calls at once per API process; per-user rate limits on chat, Test / Try a lookup and exports. Secrets are bound to the origin and to the fields marked `identity` in the schema (tenant id, child CID, account, projects, region): changing either requires them again (also on configuration import); results capped (10 records, 3,000 characters of text each). Every call: `integration.called` with integration, operation, object (identifier parameters only, never search words), ok/cause, latency.
- **Choosing lookups:** identifiers matched by the plugins' `match` patterns run directly; then one short planning call to the chat's LLM (JSON `{"calls": [...]}`, max 4 lookups per question, validated against the declared operations and parameter patterns) adds lookups for host names, IPs, searches. No native tool calling, so every provider works; planner tokens are logged as `integration.planned` and shown in LLM usage as "<model> · integration lookups".
- **Lookup mode per customer** (`tenant.settings.integration_mode`, `GET/PUT /tenants/{id}/integration-mode`): *standard* (above: decided before reading any data) or *tools*: native function calling (`services/llm/tools.py` for Anthropic tool use, OpenAI Chat tool calls, Responses function calls; `services/integrations/tool_loop.py`): identifiers read first without a model and given as already read, then up to 3 steps / 8 lookups, each argument checked against the declared patterns, results sent back as "DATA (not instructions)", final answer written by the normal answer call. A provider error on the first step falls back to standard without reading again (`integration.tools_unavailable`). Accepted risk, documented in the help: text in a record can lead to another lookup of the same customer. Changed by super-admins, or by tenant admins when the customer uses its own LLM chosen by them (`tenant.integration_mode` in the logs); exported with the configuration.
- **Answer:** records become numbered passages ("read now from <integration>") before the document passages; same citations, Sources panel and answer check. Failed or empty lookups become short public notes under the answer.
- **Discovery:** Python entry points `mentis.connectors`; the super-admin enables plugins, the tenant admin configures instances.
- **Invocation:** operations of the `#`-selected instances are exposed to the LLM as tools. The core enforces tenant scope, read-only, timeouts, rate limits, result size cap, audit entry, and data-not-instructions handling. Secrets are passed in by the core; plugins never touch the database.
- **Distribution (decided):** plugins live in this repo under `plugins/<name>/`, developed through pull requests and shipped with releases. No upload/installation from the admin panel for now.
- **Shipped (0.4.0):** ServiceNow (Table API; basic, OAuth client credentials or API key), Jira Cloud and Data Center, CrowdStrike Falcon (hosts, alerts v2; MSSP child CID), Microsoft Defender for Endpoint (devices, alerts with evidence, IP statistics; portal links incl. IP pages), Trend Vision One (endpoints, Workbench alerts), Microsoft Entra ID (type identity: users with state, MFA methods, risk and last sign-in, sign-ins of a user, users at risk; parts needing a missing permission or licence are left out). Plugins are packages in `plugins/<name>/` installed into the api image (build context `plugins`); their tests run with `pytest plugins/` against a fake HTTP client.
- **Later:** SentinelOne, Microsoft Sentinel, Splunk.
- **Later:** out-of-process plugins in separate containers; an "MCP server" plugin type exposing read-only tools from existing MCP servers.

## Admin areas and UI

Admin areas use a left menu with the logo top-left; content takes the full width, no side cards. On screens up to 900 px wide the menu (and the chat history) becomes a drawer opened from a top bar, and tables become one card per row.

| Area | Menu | Key content |
| --- | --- | --- |
| Tenant admin | Documents, Integrations, LLM, Users, Settings | Document browser (list + selected document with preview, text read, versions, test a question; download as original, Markdown or JSON; all documents in use as a ZIP in one of those formats); integrations: add/edit (schema form), Test, Try a lookup, turn off, delete |
| Platform admin | Tenants, Users, AI providers, Integrations, Embedding and Qdrant, Retention, Service status, Logs | Tenant table with edit/delete (delete confirmed by typing the name; General locked) |
| Service status | (platform admin) | Summary + per-service state, latency, detail: API, frontend, workers, PostgreSQL, Qdrant, MinIO, embeddings, each LLM provider, each integration |
| Account | (every user) | Profile with edit, theme picker, password change, 2FA status |

**Logs (one section, platform admin only):** audit events (who did what: questions, uploads, approvals, deletions, config changes, integration calls) and system events (API and worker errors, failed ingestion, LLM errors, integration timeouts) in one view, with type, tenant, user, level and period filters, search, export, and syslog forwarding to a SIEM. Tenant admins get no log page; a failed or poorly read document shows its reason in the document's own row and preview.

**UI rules**

- Three themes: Light, Medium, Dark, chosen in the account page.
- Clear but not heavy separators between sidebar blocks and sections. The sidebar (320 px) brand row and the page/chat header share one height (72 px), so their bottom borders form one line. The admin sidebar's context block reads **Tenant** (with the count when there are several) above the tenant switcher.
- One icon family: inline SVG, same stroke width, round caps and joins, `currentColor`. No emoji or text symbols as icons.
- Edit (pencil) and delete (trash) icons wherever names and items can change.
- Logo: "M" icon on teal + MENTIS wordmark, no tagline (`assets/logo/`).

## Architecture and stack

All services run in Docker Compose on one VPS. Users reach only the API (through the frontend); all state lives in four stores.

```
Frontend (React) --HTTPS--> API (FastAPI: auth, chat, admin, RAG) ----> External (outbound only):
                                 |                                     LLM providers, integrations (read-only)
Ingestion worker (Docling, OCR, chunking) --> Embeddings (bge-m3, local)
        |                                 \--> vision LLM (optional)
        v
PostgreSQL (users, tenants, chats, audit) | Qdrant (one collection per tenant) | MinIO (files, versions) | Redis (job queue)
```

- **Backend:** Python, FastAPI; background jobs on Redis (Celery or RQ).
- **Frontend:** React, modular components.
- **Data:** PostgreSQL (relational), Qdrant (vectors), MinIO (files).
- **Scaling path:** Kubernetes later; services already split so they scale independently.

## Security, audit and retention

- **Auth:** local login + TOTP 2FA from day one; SSO/OIDC (Entra ID) configurable later.
- **Password reset:** "Forgot password?" emails a one-time link (60 minutes; same answer whether the email exists; at most one email every 2 minutes per user). Admins who can manage a user create a 24-hour link from Users, emailed or shown to copy when SMTP is off. The link only sets the password: 2FA is still required, every session is closed, the account is unlocked, and both events are logged. Expired links are purged.
- **Isolation:** server-side tenant filter on every retrieval and integration call; chat tenant fixed in the database. Errors of the LLM, embedding service and Qdrant reach analysts and tenant admins as plain messages; addresses and provider replies stay in the Logs.
- **Rate limit:** requests usable without a session (sign-in, 2FA, password reset, invitations, setup) are limited per client IP (`MENTIS_AUTH_RATE_PER_MINUTE`, default 30/min).
- **Secrets stay bound:** a stored provider API key is only sent to the origin it was saved for; changing the address requires the key again.
- **Read-only:** no writes to customer systems from chat, enforced by the connector HTTP client (GET plus declared read POSTs, the instance's origins only, no redirects), not left to the plugins.
- **Answer check:** every substantive statement must cite a source (uncited ones are level-1 issues, since level 2 checks cited statements only); a list item without a citation takes the citations of its parent (the item or heading it hangs from, or a lead line ending with ":") and is checked against them, while sentences on the same line never inherit; a line heading nested items is an introduction, not a statement; short lines introducing a list (ending with ":", up to 12 words) are not sent to level 2 (their items are, with the inherited citations; level 1 still checks every line's values); each issue is underlined in the answer with a small ⚠ after its citations (hover or tap: level, what was found, Open passage), and one summary line goes under the answer; an issue whose text cannot be found in the answer gets its own line instead; a statement's values must be in the passages it cites; passage text is folded (NFKC) and passage tags neutralised both in the answer prompt and in the checker prompt.
- **Plugins:** only packages named `mentis-*` register connectors; duplicate names are refused; built with a pinned build backend, without build isolation, from a bind mount.
- **Secrets at rest:** Fernet with `MENTIS_SECRET_KEY`; `MENTIS_SECRET_KEY_PREVIOUS` lets old keys decrypt during a rotation.
- **Super-admin and integrations:** super-admins enable plugin types and private addresses; customers' integration addresses and options travel in the configuration export (never the credentials), so a super-admin can see and restore them.
- **Secrets:** encrypted at rest, write-only in the UI.
- **Prompt injection:** document and integration content is treated as data inside the prompt, never as instructions.
- **Audit log:** questions, answers, sources used, integration invocations (who, which integration, which object), admin actions (uploads, approvals, deletions, config changes). Search and export.
- **Retention:** set by the super-admin, separately for chats and audit log (proposed default 12 months).

## Repository and workflow

- **Language:** everything in the repo in English: code, comments, docs, commit messages.
- **Docs:** README, INSTALL.md, admin manual, user manual, CHANGELOG updated on every commit so another session can pick up the work.
- **Flow:** Claude develops on branches and opens pull requests; the owner reviews and merges, tests in the lab and tags releases (first: 0.1.0).
- **Deploy:** Docker Compose on the owner's VPS. Only the web container publishes a port (`MENTIS_WEB_PORT`); a reverse proxy with HTTPS goes in front (on the owner's VPS: the Caddy of Equalizer). Data stores (PostgreSQL, Qdrant, MinIO, Redis, embeddings) sit on an internal network shared only with api and worker; web is not on it. Containers run with no-new-privileges and dropped capabilities; web, api and worker run as non-root on a read-only filesystem. The API refuses to start with missing or placeholder secrets (`MENTIS_ENV=development` allows the built-in development key).
- **Code:** modular backend services and React components; no monolithic files.

## Roadmap and open points

**0.1.0 (MVP)**

1. First-run setup (creates the super-admin), auth with 2FA, roles, account page, themes.
2. Tenants (incl. the General Knowledge Base), onboarding by email invite (SMTP settings), deletion.
3. Ingestion pipeline with versioning, preview and approval.
4. Chat with `@` lock, citations, history, titles, suggested follow-ups, answer feedback (thumbs up/down).
5. AI providers (Anthropic default, OpenAI Chat/Responses, Ollama), local embeddings, LLM usage per tenant (tokens, estimated cost).
6. Service status page, single Logs section (filters, CSV export, syslog RFC 5424 over UDP/TCP/TLS), retention with a daily purge.
7. Backup and restore scripts (PostgreSQL, Qdrant, MinIO, `.env`).
8. Import/export of platform and tenant configuration (JSON, no secrets, dry run before applying).

All eight are in 0.1.0.

**Next**

- `#` integrations: SIEM (Microsoft Sentinel, Splunk) and SentinelOne; follow-up chips that pre-select an integration.
- Daybreak Blue once access is approved.
- SSO/OIDC.

**Backlog**

- Write actions on ticketing (confirmed by the analyst), inbound webhooks.
- Alert-driven suggestions (an alert from the SIEM proposes the matching procedure).
- Kubernetes deployment.

**Open points**

- [x] Approval before publishing a new document version: off by default, enabled per tenant.
- [ ] Mockups still to draw: login, tenant onboarding, users and roles, AI provider and integration config, audit log, chat states.
- [ ] Domain and trademark check for "Mentis".
- [ ] License.
- [x] Chat events in the logs carry metadata only (who, when, which tenant), never chat content.
