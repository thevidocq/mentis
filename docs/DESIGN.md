# Mentis – Project Design Document

_Last updated: 2026-11-25. Living version: the shared design doc; this file is the repo copy._

## Overview

Mentis is a standalone, multi-tenant web app: an AI assistant that answers SOC analysts from each customer's own documentation, with sources cited on every answer.

- **Problem:** a SOC serving many customers has procedures, escalation matrices and runbooks spread across PDF, Word, Excel and PowerPoint, different for every customer.
- **Answer:** one RAG index per customer tenant, plus a shared General knowledge base, queried through a chat interface.
- **Principle:** analysts consult only. Mentis never writes to customer systems.
- **Positioning:** the core is domain-agnostic; SOC is the first vertical pack (labels, integration catalog, system prompt). Anything SOC-specific lives in configuration or plugins, not in the core.
- **Style:** modular code, Docker Compose first, Kubernetes later, React frontend.

## Users and roles

| Role | Area | Can do |
| --- | --- | --- |
| Super-admin | Platform admin | Onboard, edit and delete tenants; manage the General tenant; configure AI providers, embeddings, retention; view service status and audit log |
| Tenant admin | Tenant admin | Upload, version, preview and approve documents; choose tenant LLM; configure integrations; manage tenant users |
| Analyst | Chat + account | Chat (read-only consultation), own profile, theme, password |

- Analysts see the **global** list of onboarded customers, not only assigned ones.
- Every user has an account page: profile, theme (Light / Medium / Dark), password change, 2FA status.

## Tenancy model

- **Customer tenant:** own documents, vector collection, LLM settings, integrations, users.
- **General tenant:** flag `global`, exactly one. Included automatically in every retrieval. Managed by the super-admin, read-only for tenant admins. Cannot be deleted.
- **Precedence:** when General and customer documents disagree (escalation, SLA), the customer document wins; the answer may flag the conflict.
- **Opt-out:** per-tenant setting "Include General documentation", default on.
- **Isolation:** the tenant filter is applied server-side on every query, never left to the prompt or the frontend.
- **Deletion:** removes documents and versions, Qdrant collection, chats, LLM and integration settings. Audit log is kept per retention. Confirmation requires typing the tenant name.

## Chat experience

One chat = one customer scope, locked at the first message; integrations are chosen per message.

**Layout**

- Left sidebar, clearly separated blocks: logo + "New chat" (light outlined button), history search, history grouped by day, account link at the bottom.
- History items show title and `@customer`; the active chat has rename and delete icons.
- Header: chat title, locked customer badge, LLM badge (brain icon + configured instance name).

**`@` customer scope**

- `@` opens the global customer list: "All customers" (default) plus every onboarded tenant.
- The scope is fixed by the first message. Afterwards `@` shows the list greyed out with "Customer locked for this chat" and a link to start a new chat.
- A chat started on "All customers" stays on "All customers".
- The backend uses only the tenant stored on the chat, whatever the frontend sends.

**`#` integrations**

- `#` lists only the integrations enabled for the chat's customer, grouped by type (Ticketing, EDR, SIEM).
- Multi-select; selections show as removable chips in the input and on the sent message; they apply to that message only.
- No `#` = documentation only. In "All customers" chats `#` is disabled.

**Answers**

- Every answer states which customer it refers to (and "+ General" when used).
- Citations: documents as [1], [2] (document, version, page/sheet/slide); live integration data as [A], [B] (source, object, read time).
- If the documentation does not cover the question: "Not found in <customer> documentation", never an invented procedure.

**Titles**

- Generated after the first exchange by a short call to the chat tenant's LLM (4–6 words, no customer name).
- Fallback: first 60 characters of the question. Manual rename locks the title.

## Document ingestion and versioning

Uploads run as background jobs; a new version reaches answers only once indexed (and approved, when approval is on).

**Pipeline**

1. Upload (PDF, DOCX, PPTX, XLSX) → original stored in MinIO.
2. Parse with Docling: headings, order and tables preserved. Scanned pages go through OCR (Tesseract).
3. Excel handled as tables (sheet, header, rows), not flattened text.
4. Optional vision LLM (per tenant) describes images and diagrams.
5. Chunk with metadata: `tenant_id`, `doc_id`, `version`, `active`, page/sheet/slide.
6. Embed and write to the tenant's Qdrant collection.

Apache Tika is set aside for now.

**Known weak spots** (why preview exists): poor-quality scans, diagrams without vision, Excel with merged cells or several tables per sheet, multi-column or shape-heavy slides.

**Preview and approval**

- Side-by-side view: original page on the left, extracted text on the right.
- Per-page quality flags: native text vs OCR, OCR confidence, tables found, empty or unreadable pages.
- "Test a question" box scoped to that document before publishing.
- Optional per-tenant approval: the new version stays inactive until the admin approves it.

**Versioning**

- Same file name = new version. Only the active version is searchable; older ones stay viewable and can be restored.
- Each version records date, uploader and an optional note.
- Documents can be renamed and deleted (with confirmation).

## AI layer

LLM is configurable per tenant; default for the prototype is Claude Haiku. Embeddings stay local.

| Provider type | Use | Notes |
| --- | --- | --- |
| Anthropic | Claude Haiku (default) | API key |
| OpenAI Chat Completions | OpenAI cloud, vLLM, compatible endpoints | `/v1/chat/completions` |
| OpenAI Responses API | Internal gpt-oss (vLLM) | `/v1/responses`, reasoning auto-on for gpt-oss/o-series, API key optional |
| Daybreak Blue | OpenAI defensive-cyber model (`gpt-daybreak-blue-latest`) | Requires approval in OpenAI's Daybreak program |
| Ollama | Local models | No key |

- Every provider: test connection, model discovery, failover to a secondary provider.
- **Embeddings:** local by default (bge-m3, multilingual). Other providers configurable (Ollama, OpenAI-compatible endpoints).
- **Vector DB:** Qdrant only, one collection per tenant.
- **Retrieval:** customer chunks + General chunks (if enabled), active versions only, score threshold; customer wins on conflict.
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

**Plugin model**

- **Contract:** manifest (name, version, type, vertical, compatible core API), JSON Schema config (admin form generated from it), `test_connection`, read-only typed `operations`, `run` returning normalized models (Ticket, Device, Alert) plus source metadata for citations.
- **Discovery:** Python entry points `mentis.connectors`; the super-admin enables plugins, the tenant admin configures instances.
- **Invocation:** operations of the `#`-selected instances are exposed to the LLM as tools. The core enforces tenant scope, read-only, timeouts, rate limits, result size cap, audit entry, and data-not-instructions handling. Secrets are passed in by the core; plugins never touch the database.
- **Distribution (decided):** plugins live in this repo under `plugins/<name>/`, developed through pull requests and shipped with releases. No upload/installation from the admin panel for now.
- **Packs:** core ships ServiceNow and Jira; the SOC pack ships Defender, CrowdStrike, SentinelOne, Sentinel, Splunk.
- **Later:** out-of-process plugins in separate containers; an "MCP server" plugin type exposing read-only tools from existing MCP servers.

## Admin areas and UI

Admin areas use a left menu with the logo top-left; content takes the full width, no side cards.

| Area | Menu | Key content |
| --- | --- | --- |
| Tenant admin | Documents, Integrations, LLM, Users, Settings | Document table with versions, rename/delete, upload, preview |
| Platform admin | Tenants, General documentation, AI providers, Embedding and Qdrant, Retention, Service status, Audit log | Tenant table with edit/delete (delete confirmed by typing the name; General locked) |
| Service status | (platform admin) | Summary + per-service state, latency, detail: API, frontend, workers, PostgreSQL, Qdrant, MinIO, embeddings, each LLM provider, each integration |
| Account | (every user) | Profile with edit, theme picker, password change, 2FA status |

**UI rules**

- Three themes: Light, Medium, Dark, chosen in the account page.
- Clear but not heavy separators between sidebar blocks and sections.
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
- **Isolation:** server-side tenant filter on every retrieval and integration call; chat tenant fixed in the database.
- **Read-only:** no writes to customer systems from chat.
- **Secrets:** encrypted at rest, write-only in the UI.
- **Prompt injection:** document and integration content is treated as data inside the prompt, never as instructions.
- **Audit log:** questions, answers, sources used, integration invocations (who, which integration, which object), admin actions (uploads, approvals, deletions, config changes). Search and export.
- **Retention:** set by the super-admin, separately for chats and audit log (proposed default 12 months).

## Repository and workflow

- **Language:** everything in the repo in English: code, comments, docs, commit messages.
- **Docs:** README, INSTALL.md, admin manual, user manual, CHANGELOG updated on every commit so another session can pick up the work.
- **Flow:** Claude develops on branches and opens pull requests; the owner reviews and merges, tests in the lab and tags releases (first: 0.1.0).
- **Deploy:** Docker Compose on the owner's VPS.
- **Code:** modular backend services and React components; no monolithic files.

## Roadmap and open points

**0.1.0 (MVP)**

1. Auth with 2FA, roles, account page, themes.
2. Tenants (incl. General), onboarding, deletion.
3. Ingestion pipeline with versioning, preview and approval.
4. Chat with `@` lock, citations, history, titles.
5. AI providers (Anthropic default, OpenAI Chat/Responses, Ollama) and local embeddings.
6. Service status page, audit log, retention.

**Next**

- `#` integrations: ServiceNow and Jira first, then EDR and SIEM plugins.
- Daybreak Blue once access is approved.
- SSO/OIDC.

**Backlog**

- Write actions on ticketing (confirmed by the analyst), inbound webhooks.
- Alert-driven suggestions (an alert from the SIEM proposes the matching procedure).
- Kubernetes deployment.

**Open points**

- [ ] Approval before publishing a new document version: default on or off?
- [ ] Mockups still to draw: login, tenant onboarding, users and roles, AI provider and integration config, audit log, chat states.
- [ ] Domain and trademark check for "Mentis".
- [ ] License.
