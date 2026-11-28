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
- A tenant admin grants only customers it has (all only with `all_tenants`), sees only users whose customers are all its own (a user or invitation with no customer, General Knowledge Base at most, only if it has all customers: a tenant admin of the General Knowledge Base alone manages no user), and cannot change its own role or customers. Changing a user's customers revokes its sessions. Saved answers that used a customer the user no longer has are hidden (answer, sources, follow-ups) and never sent back to the LLM as history: each answer records the tenants whose passages the model read (`chat_messages.searched`, cited or not), older answers are judged by their citations. Titles of "All customers" chats are the question, never model text. Deleting a document or a customer removes the answers that used it (text, sources, follow-ups; `services/chat_redaction.py`), not only its index entries. A shared link closes when the chat's customer is disabled, or when the owner of an "All customers" chat has no customer left.
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
- **Answer check** (`services/answer_check/`): level 1 compares critical values (phones with or without a country code but never missing digits nor with a prefix the passage does not give, groups split by spaces read as phones; e-mails, URLs, domains (a domain also matches the host of a passage's address or e-mail), IPs with port, IPv6, MAC addresses, Windows paths and registry keys, event IDs, ports, extensions, any other number (counts, thresholds; it matches the same number written anywhere in the passage: a date, a time, an address with port, a range, "1,000" = "1000"; numbers naming the answer's own structure, "Step 1", "the 2 steps below", and "24/7" are not values), times in 24 h, AM/PM, "8 PM", "9-11 PM", "21h" or "9.30", durations up to months and years including "1h30", "1½ hours", "45-minute", "fifteen minutes", compound ("1 hour 30 minutes" = 90 min) and ranges (either bound of a passage's range is accepted), percentages, dates in any order of writing, ticket/CVE/MITRE codes, any hex run of 30–130 characters as a hash; both texts NFKC-normalised with Unicode spaces and dashes made plain, invisible characters removed and defanged indicators ("10[.]0[.]0[.]1", "hxxps") folded; read from the text without paired Markdown markers, so bold cannot split a number) with the passages the statement cites, and each issue keeps its statement so the chat marks it there and level 2 joins only verdicts of the same statement; it flags answers without citations; level 2 asks a checker model (role `checker` in AI providers; per customer: chosen checker > the customer's own LLM > default checker > the answering model) whether each statement is supported (every unit, see below; the statements are sent as the analyst reads them and as data) (JSON verdicts; "Document/Claim -> Yes/No" for MiniCheck-style models). Level 2 runs in groups of 10 statements (≤ 24 in all; any beyond are reported as *not checked*, never as matching; verdicts read whether the model writes 2, "S2", a list, a range "S1-S3", another key such as "statement", or the statement's own text (digits inside quoted text are never read as numbers); a rejection without a readable number makes the check unavailable, never "supported"; "Matches the sources" needs the checker to have read at least one statement), each call limited by the customer's `check_max_tokens` (500–16000, default 2500 or the checker's own max tokens if higher, **LLM** page, tenant admin even when models are locked); an empty or unreadable reply is retried once; failures are logged with the provider's stop reason (`LLMReply.stop`: end_turn, max_tokens, refusal, length…), tokens used and the limit, and so are answers cut by Max answer tokens. Modes per tenant: warn (default; level 2 after the response, the browser polls), hide (both before the response; one rewrite with the problems, then "Not found", hidden text kept for audit only; statements beyond the 24 checked count as a problem, so hide mode shows only fully checked answers), off (level 1 only). Results on `chat_messages.answer_check`; issues carry the level(s) that found them, shown to analysts as Level 1 / Level 2 / Level 1 + 2. Answers go back to the LLM as history without their [n] markers (they point to that answer's passages), flagged ones with a note. In hide mode the rewrite gets each problem with its reason; the last statement of an answer cut by the token limit is not reported as uncited. A "not found" reply that cites passages is a partial answer and is shown and checked as one; one with uncited values shows the standard not-found text. Logged as `chat.checked`; costs in usage as "<checker> · answer check". Answers and checks use temperature 0 (retried without it when a model refuses the parameter).
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
- **Links to live records**: the prompt asks the model to write a record's id as a link to the "Link" given in its passage; links that do not come from a record found for this question are reduced to their text; addresses written in a passage stay as plain text, any other address is removed (also inside a link's label, in fullwidth characters, with one or three slashes, or as a lowercase host name with a known top-level domain and a path; "ASP.NET/IIS" or "Node.js/npm" stay), and a cited record the answer does not link gets an "Open: [product kind id](url)" line under the answer (added after the answer check, like the notes on failed lookups). The browser renders `[text](url)` as a link only for URLs of the answer's cited records.
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

- The first 60 characters of the first question (the model writes no title: one written from the passages could repeat a value, and titles stay visible when an answer is hidden). Manual rename locks the title.

## Document ingestion and versioning

Uploads run as background jobs; a new version reaches answers only once indexed (and approved, when approval is on).

**Pipeline**

0. **From a link** (`services/link_sources.py`, `POST /tenants/{id}/documents/link`): a public URL is read through the integrations' guarded client (`connectors/http.SafeHttp`: HTTPS and public addresses only, whatever the integrations' *allow_private* setting, the address resolved once and pinned, loopback/metadata/Mentis' own services refused, no redirects, size cap = upload limit or 20 MB if lower, after decompression, 60 s deadline). GitHub file links are read from raw.githubusercontent.com. HTML is converted to Markdown with lxml (`ingestion/htmltext.py`: `<main>` else `<body>`, no scripts, navigation, the site's header and footer, form controls or hidden elements; headings (without permalink signs), lists (nesting capped at 6; code blocks and tables inside an item kept as indented blocks), quotes, tables (nested tables flattened into the cell), code kept; links as text; the page's charset honoured, UTF-8 when none is declared; output capped at 5 M characters); Markdown/text, PDF, JSON, YAML and CSV are kept. The result goes through the same upload checks and becomes a version like an upload. The document stores `source_url`, `source_check` (6h, 1d, 7d, manual), last check time, status (new_version, unchanged, error) and error, ETag and Last-Modified (migration 0014). The worker's maintenance loop checks due links every 10 minutes (Redis lock, one replica, 20 per round, active customers only); **Check now** (`POST …/{doc}/link/check`) and the schedule (`PATCH …/{doc}/link`) are tenant-admin actions. A check sends conditional headers; 304 or the same SHA-256 as the latest version (any state, so content that failed is not stored again until it changes) = unchanged; one check at a time per document (row lock); otherwise a new version (note "Page changed"). A failed read keeps the version in use and shows the reason (overview: Needs attention). A linked document refuses manual new versions; a page that turns into another file type is refused. Audited: `document.link_added`, `document.link_refused`, `document.link_updated`, `document.link_checked`, `document.link_changed`.

1. Upload (PDF, DOCX, PPTX, XLSX, Markdown `.md`/`.markdown`, JSON, CSV, TSV, YAML `.yaml`/`.yml`, PNG, JPEG `.jpg`/`.jpeg`; up to 50 MB) → validated (extension matches content; text formats must be UTF-8 and parse (YAML composed only, never constructed, at most 200,000 values); pictures by header, at most 50 million pixels; no macros, no encrypted Office files, zip-bomb guard; a PDF that needs a password to open fails in the worker, one that only restricts printing or copying is read) → original stored in MinIO under a generated key.
2. The ingestion worker (separate container, RQ on Redis, CPU/RAM limits, 30-minute timeout) parses the file into pages:
    - PDF: one page per page; native text via pdfplumber with each table in its place as a Markdown table (table cells are not read a second time as text); pages with almost no text, or mostly an image with little text (a scan with a printed footer), are rendered (pypdfium2) and read with Tesseract OCR (English + Italian) with a confidence score; pictures covering at least 5% of a text page are OCR'd too ("Text in image:"); every page is rendered as an image for the preview.
    - DOCX: split into sections at top-level headings; text read from the XML (tracked insertions, content controls, fields, hyperlinks; never deleted text), text boxes, list numbers as "1." or "-", tables with merged cells filled and nested tables inside their cell, page headers and footers once ("Page header:").
    - PPTX: one page per slide; title, text (auto-numbered paragraphs as "1.", levels indented), tables, speaker notes, and OCR of pictures, placeholder pictures included (screenshots, diagrams).
    - XLSX: one page per sheet as a Markdown table (values as shown: percentages, dates without midnight, whole numbers; not formulas); a merged range gives its value to every cell it covers; a lone title above a wider table becomes a caption; hidden sheets are flagged.
    - Markdown: one section per top-level heading. JSON: a Mentis export keeps its pages; other JSON is rendered as Markdown, numbers as written (1.10 stays 1.10), a list over 2,000 rows says how many were not read. Web pages: cells spanning rows or columns fill every slot they cover.
    - CSV / TSV: one table (delimiter detected: comma, semicolon, pipe, tab; no consistent delimiter → one column of lines; TSV unquoted), same row limit as a sheet, at most 500 columns.
    - YAML: one section per YAML document, labelled by `title`/`name`/`id` (Sigma rules, playbooks), text kept as written in a code block, comments with the document they precede; values counted from parser events (libyaml) before any tree is built, so anchors are never expanded and oversized files stop early.
    - PNG / JPEG: one page read with OCR (upright by EXIF, transparency on white), confidence score, the picture kept as preview.
    - The Docling parser, when on, handles PDF and Office files only; the other formats always use these readers.
3. Parsing, and cutting the pages into chunks, runs in a forked child (`ingestion/isolated.py`) in a process group of its own (killed whole when it ends or the job times out, so OCR programs never outlive it) with an address-space limit (`MENTIS_PARSE_MEMORY_MB`, standard readers), a CPU limit (`MENTIS_PARSE_CPU_SECONDS`) and an OCR time limit per picture (`MENTIS_OCR_TIMEOUT_SECONDS`, default 600); readers cap their output (5 M characters per Word file or web page, 5,000 rows per table, nested tables 5 deep, merged-cell values repeated only when short, table slots ≤ 250,000; Markdown tables keep at most 200 non-empty columns and 1 M cells; text boxes 3 deep, each reading its own paragraphs), so a crafted file fails alone. Web pages added from a link are converted in the API and worker processes with the same bounds.
4. Quality flags per page: OCR + confidence, low confidence (< 60%), empty, merged cells, hidden sheet, truncated. Soft hyphens and zero-width characters are removed.
4. Chunks are built per page (never across pages, so citations stay exact), around 1,500 characters, tables kept whole or split by rows with the header repeated, fenced code blocks kept whole or split by lines with the fence repeated (a `#` line inside code is never a heading), long text split at line ends, then sentences, cut only at a space (a name never leaves its phone number), a table found under a caption line or with any Markdown separator, a heading or a short lead-in ("Call in this order:") always kept with what follows; each chunk carries its section path ("Ransomware > Tier 2 > Contacts"), embedded with the chunk and shown to the model.
5. Embedding (OpenAI-compatible endpoint; default local TEI container with bge-m3; answers read streamed up to 64 MB, one finite vector per text in order, all of one size, ≤ 8192 dimensions, else the version fails; a stored API key, or the one from `.env`, is sent only to the origin it was saved for: moving to a new origin without a new key drops the stored key, also through a configuration import; `MENTIS_EMBEDDING_ALLOWED_URLS` limits the addresses the panel accepts, since every document and question goes there; a move is logged as a warning) and upsert into the tenant's Qdrant collection (`mentis_<tenant>`), payload: tenant, document, version, chunk, active. Indexing is the last step: if it fails, the version fails and the active one stays.
6. Activation, approval and restore update the `active` flag in Qdrant, but answers do not rely on it: each search is limited to the versions in use as PostgreSQL lists them (`MatchAny` on version_id), so a flag left stale by a failed commit can neither hide a document nor show an old version. PostgreSQL is the source of truth: every search hit is re-checked against the database (chunk, tenant, version ready and active), so a stale index can never surface a version not in use.
7. Changing the embedding model requires a full reindex (rebuilt from stored chunks, no re-parsing); uploads fail with a clear reason until it is done. While it runs (and after a failure once clearing the index has started, even midway) retrieval refuses with a public message, so no answer comes from a half-built index; the new model is recorded only when every version is indexed (each tried twice; failures named); versions that become ready meanwhile are indexed in a last pass.
8. **Reprocess all documents** (`POST /platform/embedding/reprocess`, worker `reprocess_all`): every ready version is parsed again from its original file and its pages, chunks and points are swapped in place (new points written before the old chunks and points are removed; approval and activation unchanged). A version that fails keeps its reading and is listed; one whose old points could not be removed after its new reading was committed (three attempts) is listed apart ("old index entries remain: run Reindex"), and the daily sweep removes points of ready versions whose chunk no longer exists (not while a reindex or reprocess runs). One job at a time (reindex or reprocess).
9. Retrieval: a short question (≤ 8 words) is searched alone and with the previous question, each passage keeping its best score. "All customers" chats use the General Knowledge Base only when every customer in scope allows it.

**Parser choice (decided):** the default parser is the "standard" stack above, fully tested. Docling is available as an option (`MENTIS_PARSER=docling`, image built with the `docling` extra) but is not verified yet: it needs PyTorch and HuggingFace models that the development environment cannot reach. It becomes the default only after a lab test on real customer documents. Apache Tika stays set aside.

**Known weak spots** (why preview exists): poor-quality scans, diagrams without vision, Excel with merged cells or several tables per sheet, multi-column or shape-heavy slides.

**Deleted documentation in saved answers**

- Each answer records the customers (`searched`) and the documents (`read_documents`, migration 0016) whose passages the model read, cited or not. Deleting a document or a customer removes the answers that read it (text, sources, follow-ups, check details); the question stays.
- The rule is also applied on every read (`chat_visibility`): an answer citing a document or version, or having read a document, that no longer exists (deleted, purged by retention) is hidden, so an answer saved while its document was being deleted never shows it; the save itself re-checks and removes it. The background level-2 check re-reads the message, locked, before writing, and never writes on a removed answer.
**Preview and approval**

- Tabs **Preview** (the original page: PDF page image or the PNG/JPEG picture; for the other formats the text read) and **Text read** (the extracted text, with how it was read), one page at a time.
- Per-page quality flags: native text vs OCR, OCR confidence, tables found, empty or unreadable pages.
- "Test a question" box scoped to that version (works on pending versions too), showing the passages Mentis would use and their match score.
- Optional per-tenant approval: the new version stays inactive until the admin approves it. Setting `approval_by_another` (off by default; tenant admins on the Settings page, also with the General Knowledge Base selected; super-admins through the API): the person who uploaded a version (for a version read from a link by the schedule, the person who set the link) cannot approve it (409), only reject it; a self-approval allowed by the setting is logged as a warning (`document.version_approved`, `self_approved`).

**Versioning**

- Same file name (case-insensitive) = new version; renaming keeps the extension. Only the active version is searchable; older ones stay viewable and can be made active again.
- A failed or rejected version never replaces the active one. An upload whose SHA-256 matches any version of any document of the same customer (all file types; failed and rejected versions excepted) is refused (409) with the document and version it matches (`versions.duplicate_message`) and logged as `document.upload_refused`; other customers are not compared.
- Each version records date, uploader and an optional note.
- Documents can be renamed and deleted (with confirmation). Deletion removes the rows first (answers stop at once), then files and vectors; anything left by an unreachable MinIO or Qdrant is removed by the daily storage sweep (no row = leftover; rows are always written before files and vectors).
- Retention of old versions (super-admin, default all): per document the version in use, the latest and pending ones are always kept; older ones beyond N are deleted with files, pages, passages and vectors.
- Storage: page images WebP; Qdrant vectors on disk (memory-mapped; existing collections moved by the sweep); container logs rotated; backups rotated (`MENTIS_BACKUP_KEEP`).
- **Upload a new version** (⋯ menu) of a selected document accepts any file name of the same type (`document_id` on upload); not for documents read from a link, which get their versions from the link only (also refused by name).
- The Documents page is a document browser: the list on the left (search; All / In use / To review; *Needs attention* grouped first), the selected document on the right in one column: a header with name, state, a *from link* chip and a facts line (type, size, pages, how it was read, date, note), Approve/Reject or Retry when needed, Download (menu: Original, Markdown, JSON; also on each version) and a ⋯ menu (Upload a new version, Rename, Versions, Delete); then the **Read from a link** panel for linked documents, read warnings as banners, and the tabs, with a *Viewing vN · back to the version in use* note when an older version is on screen; **All** above the list downloads every document in use as a ZIP (originals, Markdown or JSON, with `manifest.json`; originals capped by `MENTIS_EXPORT_MAX_MB`). Markdown = the pages read with a header (customer, version, file, date, SHA-256); JSON (`mentis-document/1`) = metadata, pages and indexed passages, to import elsewhere. Audited `document.exported`, `documents.exported`, and the tabs Preview, Text read, Versions, Test a question. The selection is in the address (`?doc=`); without one the right side shows an **Overview** (`GET /tenants/{id}/documents/overview`, counts only): documents in use, pages read and OCR, passages, embedding model, questions in chats on the customer in 30 days with not-found count (not for the General Knowledge Base), needs-attention list, content by type, last indexed, oldest in use, pages to check, recent uploads and approvals.

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
- **Answer:** records become numbered passages (`kind="live"`, set by Mentis, never from a name; "read now from <integration>") before the document passages; a record found twice counts once, and a list capped at 10 records says so in the passage and in a note (the prompt forbids counting a capped list); same citations, Sources panel and answer check. Failed or empty lookups become short public notes under the answer; an empty one names only identifier values checked against their pattern, never free search text (which a record could steer): "nothing found for the search".
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
- **Secrets stay bound:** a stored provider API key is only sent to the origin it was saved for; changing the address requires the key again. The embedding API key (stored or from `.env`) and the SMTP password follow the same rule: a new address, or for SMTP a new host, port or security mode, without a new secret drops the stored one, in the panel and on configuration import.
- **Read-only:** no writes to customer systems from chat, enforced by the connector HTTP client (GET plus declared read POSTs, the instance's origins only, no redirects), not left to the plugins.
- **Answer check:** every line the analyst sees is a unit of the check, recognised exactly as the chat renders it (`components/Markdown.tsx`): paragraphs and ">" notes with their lines joined, as the chat joins them ("Do not⏎isolate" is one statement), and list items ("-" or "1."), split at sentence ends; headings (`#` to `###`, or a bold line standing alone); each code block (three backticks at the start of the line open and close it; "~~~" or an indented fence is prose, as in the chat) and each table row (a line starting and ending with "|"; the first row of a table is its header, an introduction; each row is sent with its column names, "Role: Primary | Contact: Laura Bianchi"). Any unit with a letter or digit counts ("3", "Y"). A list item without a citation takes the citations of its parent (the item or heading it hangs from, or a lead line ending with ":"); a code block takes those of its lead line (a line ending with ":", a heading or a cited line; an uncited statement above a block stays a statement), else every passage the answer cites; an uncited table row takes those of the other rows, else of its lead line, else every passage the answer cites; sentences on the same line never inherit. A line heading items, code or a table is an introduction: without a citation it is checked against the passages its items cite (level 1: its values; level 2: marked "(introduces the next lines)", only the facts it states itself count). Level 1: a statement with a value, or of at least six words, and no citation is an uncited issue; level 2 reads every unit, uncited ones marked "(no citation)" against every passage the answer cites, accepted only if they state no fact or every fact they state is in those passages (so a short "Wipe DC01." cannot pass); an introduction is never the last statement of a checker call, so it is judged with the lines it introduces; code blocks and table rows are marked so the checker compares every command, argument, cell, role and negation. Level 2 runs in a 150 s budget; each issue is underlined in the answer with a small ⚠ after its citations (hover or tap: level, what was found, Open passage), and one summary line goes under the answer; an issue whose text cannot be found in the answer (inside a code block, for example) gets its own line instead; a statement's values must be in the passages it cites; passage text is folded (NFKC), stripped of invisible format characters and its passage tags neutralised in the answer prompt, the checker prompt and the hide-mode rewrite (whose problems quote the draft); model output is stored without NUL, lone surrogates or invisible format characters (bidi overrides and isolates, zero-width characters: the browser would show "2233" with an override as "3322" while both levels read "2233").
- **Plugins:** only packages named `mentis-*` register connectors; duplicate names are refused; built with a pinned build backend, without build isolation, from a bind mount.
- **Secrets at rest:** Fernet with `MENTIS_SECRET_KEY`; `MENTIS_SECRET_KEY_PREVIOUS` lets old keys decrypt during a rotation.
- **Super-admin and integrations:** super-admins enable plugin types and private addresses; customers' integration addresses and options travel in the configuration export (never the credentials), so a super-admin can see and restore them.
- **Secrets:** encrypted at rest, write-only in the UI.
- **Prompt injection:** document and integration content is treated as data inside the prompt, never as instructions.
- **Answer rules** (`services/prompts.py`): facts only from the current passages (earlier answers are not sources), a citation per statement (one number per bracket), a partial answer says what is missing (not_found only when nothing answers, one sentence without values), conflicting passages of a customer are both reported, live lists are never counted unless a total is given, names, commands and codes kept as written in any answer language. Cited passages are kept whole for **Sources** (up to 20,000 characters).
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
