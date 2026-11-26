# Mentis

Mentis is a multi-tenant AI assistant for SOC analysts. It answers questions from each customer's own documentation (procedures, escalation matrices, runbooks) and cites its sources on every answer. With `#` it also reads the customer's ticketing, EDR and identity tools (ServiceNow, Jira, CrowdStrike, Microsoft Defender, Trend Vision One, Microsoft Entra ID), read only, and links each ticket, host, alert or user it used.

> Status: `0.4.0`. See [CHANGELOG](CHANGELOG.md) and [release notes](docs/releases/).

![Answer with sources](docs/screenshots/chat-answer.png)

## What it does

- **Chat**: pick the customer with `@` (or ask about all customers). Answers come only from the documents in use. Every statement cites its source (customer, document, version, page), and the chat says "Not found" instead of guessing. Suggested follow-ups, history, feedback.
- **Integrations (`#`)**: in a chat on one customer, live tickets, devices, alerts and users from its ServiceNow, Jira, CrowdStrike, Microsoft Defender, Trend Vision One or Entra ID, cited like documents with a link to open each record in the product. Read only, enforced by the core; credentials encrypted and bound to their address.
- **One knowledge base per customer**, plus a **General** one shared by all. Tenant isolation is enforced server-side.
- **Documents**: PDF, Word, Excel, PowerPoint, with OCR for scans and images. Versions, approval before publishing, and a side-by-side preview of what Mentis read.
- **AI providers**: Anthropic, OpenAI, vLLM (e.g. gpt-oss), Ollama, with the model picked from the list each provider offers. One LLM per customer with automatic fallback. Embeddings run locally (bge-m3), vectors are in Qdrant.
- **Security**: mandatory 2FA, three roles with per-customer access (super-admin for the platform; tenant admins and analysts on the customers ticked for them), encrypted secrets, metadata-only logs.
- **Operations**: service status, Logs with CSV export and syslog forwarding to a SIEM, retention, LLM usage and cost per customer, backup/restore scripts, configuration export/import.
- Tenant admins of one or more customers, with a customer selector.
- Works from a phone: drawer menus, card tables, full-screen chat.
- Light, Medium and Dark themes, plus in-app help for each profile.

## Screenshots

The screenshots use fictional demo data.

| | |
|---|---|
| ![Customer picker](docs/screenshots/chat-customer-picker.png) `@` chooses the customer | ![Customer locked](docs/screenshots/chat-customer-locked.png) After the first message the customer is locked |
| ![All customers](docs/screenshots/chat-all-customers.png) All customers: one answer per customer | ![Not found](docs/screenshots/chat-not-found.png) Not covered by the documents: no guessing |
| ![Light theme](docs/screenshots/chat-light-theme.png) Follow-ups in the Light theme | ![Help](docs/screenshots/help.png) In-app help for each profile |
| ![Tenants](docs/screenshots/tenants.png) Tenants | ![Users](docs/screenshots/users.png) Users and invitations |
| ![General documentation](docs/screenshots/general-documentation.png) General Knowledge Base, managed by SOC admins | ![OCR preview](docs/screenshots/document-preview-ocr.png) Preview: original next to what Mentis read |
| ![Slide preview](docs/screenshots/document-preview-slide.png) Slides: tables and text in images | ![AI providers](docs/screenshots/ai-providers.png) AI providers |
| ![Add provider](docs/screenshots/ai-provider-add.png) Add a provider from a preset | ![Tenant LLM](docs/screenshots/tenant-llm.png) LLM and fallback for each customer |
| ![LLM usage](docs/screenshots/llm-usage.png) LLM usage and cost per customer | ![Service status](docs/screenshots/service-status.png) Service status |
| ![Logs](docs/screenshots/logs.png) Logs, metadata only for chats | ![Syslog](docs/screenshots/logs-syslog.png) Syslog forwarding to a SIEM |
| ![Retention](docs/screenshots/retention.png) Retention | ![Configuration import](docs/screenshots/configuration-import.png) Configuration import with preview |
| ![Invite with customers](docs/screenshots/users-invite-access.png) Invite: ticked customers, General by default, or all customers | ![Tenant admin invite](docs/screenshots/tenant-admin-invite.png) A tenant admin invites only with its own customers |
| ![Analyst with one customer](docs/screenshots/analyst-one-customer.png) An analyst sees only its customers | ![LLM chosen by the super-admin](docs/screenshots/tenant-llm-locked.png) LLM locked by the super-admin, no costs for tenant admins |
| ![Account](docs/screenshots/account.png) Account and themes | |

### On a phone

| | | |
|---|---|---|
| ![Chat](docs/screenshots/mobile-chat.png) | ![History](docs/screenshots/mobile-history.png) | ![Menu](docs/screenshots/mobile-menu.png) |
| ![Users](docs/screenshots/mobile-users.png) | ![Invite with several customers](docs/screenshots/mobile-invite.png) | ![Customer selector with search](docs/screenshots/mobile-customer-selector.png) |
| ![Account](docs/screenshots/mobile-account.png) | ![Knowledge Base switch](docs/screenshots/mobile-knowledge-base.png) | |

## Documentation

- [INSTALL.md](INSTALL.md): installation with Docker Compose, reverse proxy, upgrade.
- [docs/MANUALS.md](docs/MANUALS.md): user and admin manuals (the same pages as the in-app Help).
- [docs/DESIGN.md](docs/DESIGN.md): design, decisions and roadmap.
- [docs/security/pentest-v0.3.2.md](docs/security/pentest-v0.3.2.md): penetration test report; the authorization matrix test (`backend/tests/test_authz_matrix.py`) checks every API route for every role on each run.
