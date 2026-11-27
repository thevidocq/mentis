# Mentis v0.4.0 — Vulnerability assessment (white-box)

Date: 2026-11-26 · Scope: `main` after #23 + `feat/integration-tool-calling` (#25) · Method: white-box static review by 5 parallel reviewers (A integrations/SSRF, B authorization/isolation, C LLM/prompt injection, D web/downloads/DoS, E infrastructure/supply chain), stdlib reproduction scripts where possible. Nothing was run against a live stack.

## Summary (deduplicated)

| # | Severity | Finding | Source IDs |
|---|---|---|---|
| 1 | **High** | Answer check: uncited statements are never checked by level 2, yet the answer shows "Matches the sources" when at least one citation exists | C-1 |
| 2 | **High (conditional)** | Editing an integration keeps the stored secret when identity fields change (Defender/Entra `tenant_id`, CrowdStrike `member_cid`, Jira `projects`): with an MSSP credential valid for several customers, a tenant admin can read another customer's data | B-1 |
| 3 | Medium | SSRF by tenant admins: ServiceNow/Jira URLs accept internal/private/metadata addresses; `?`/`#` choose the path; Test is a status/port oracle; OAuth POST to any path with `#` | A-1, A-4, A-6, E-1 |
| 4 | Medium | Slow-server DoS: 15 s timeout is per read, not total; ~15 parallel Test/Try a lookup calls exhaust API threads and the DB pool (all tenants); status page hangs | A-3, D-1 |
| 5 | Medium | Decompression bomb: the 2 MB answer cap is checked after gzip decoding (781 B → 400 MB) | A-2 |
| 6 | Medium | Exports: "All" ZIP built in RAM + api `/tmp` (512 MB, shared with uploads), no cap for Markdown/JSON, no concurrency limit; nginx buffers into web `/tmp` beyond its memory limit | D-2, D-3, E-6 |
| 7 | Medium | Level 1 accepts a value found in any passage (attacker record, other customer, GKB) and truncated phone numbers | C-2 |
| 8 | Medium | Level 2 checker can be prompt-injected via cited passages (`</passage>` not neutralised there) | C-3 |
| 9 | Medium | Answer prompt: opening `<passage` tags / Unicode variants not neutralised: a record can forge a "customer runbook" passage | C-4 |
| 10 | Low | Integration mode not tied to who chose the LLM (survives LLM switch / `admin_can_set_llm=false`) | B-2 |
| 11 | Low | Super-admin can read/change customer integration settings via config export/import (secrets kept) — contradicts DESIGN | A-5, B-3 |
| 12 | Low | Status page signs in to every customer system on each load without audit; shows Jira "Connected as <name>" | B-4 |
| 13 | Low | Disabled customer: Test, Try a lookup, exports still work; chats of a lost customer still PATCH/GET | B-5, B-6 |
| 14 | Low | No rate limits on chat, exports, Test, Try a lookup (function calling: ~5 LLM calls / ~96 product requests per question) | D-4 |
| 15 | Low | Credentials over plain `http://`; userinfo in URLs stored as config | E-2, A-6 |
| 16 | Low | Backups (unencrypted by default) contain `secrets_enc` and `.env` key; no key rotation (no MultiFernet; decrypt fails silently) | E-3 |
| 17 | Low | Build: unpinned `setuptools` fetched as root for each plugin, rebuilt on every code change | E-4 |
| 18 | Low | Registry loads any installed `mentis.connectors` entry point even when not enabled; duplicate names override silently | E-5 |
| 19 | Low | Release note lacks rollback procedure (old image crash-loops at revision 0013) | E-7 |
| 20 | Low | `_safe_links`: some invented addresses survive as plain text (in brackets, `www.`, `//`, `javascript:` text) — never clickable | C-5 |
| 21 | Low | Follow-ups, live notes and hide-mode title not checked; injected text persists in history/planner context | C-6, C-7 |
| 22 | Info | Plugins context left in an image layer (no `.dockerignore`); UPN/names in `integration.called` forwarded to syslog; `trust_env` proxies; Trend link backslash; Jira projects via moved issues (suspected); ZIP name spoofing by super-admin; authz matrix gaps; outdated docstring; tools-mode cross-integration lookups (accepted risk) | A-7..A-9, B-7..B-9, C-8..C-10, D-5..D-7, E-8..E-10 |

**No issue found** (highlights): no XSS or clickable non-allow-listed link; no query injection in any of the 6 plugins; tenant isolation of integration ids, chats, exports and shared chats; origin binding of secrets, redirects, secret redaction, token cache; Content-Disposition encoding; CSRF on export GETs; CSP; non-root containers; migration 0013.


## Remediation (v0.4.1)

| # | Finding | Status |
|---|---|---|
| 1 | Uncited statements unchecked (C-1) | Fixed: uncited substantive statements are level-1 issues |
| 2 | Secrets kept when identity fields change (B-1) | Fixed: `identity` fields in plugin schemas; credentials required again (also on import) |
| 3 | SSRF via integration addresses (A-1, A-4, A-6, E-1) | Fixed: HTTPS only, address-only URLs, resolve-and-pin, blocked destinations, super-admin opt-in for private networks; host firewall rule documented |
| 4 | Slow-server DoS (A-3, D-1) | Fixed: 30 s total per call, 6 concurrent plugin calls |
| 5 | Decompression bomb (A-2) | Fixed: bounded inflation |
| 6 | Exports memory / tmp / nginx (D-2, D-3, E-6) | Fixed: cap for every format, one ZIP at a time, nginx streaming |
| 7 | Level 1 values from any passage (C-2) | Fixed: per-statement cited passages; phone suffix rule |
| 8 | Checker prompt injection (C-3) | Mitigated: tags neutralised, stricter instructions (an LLM judge stays injectable in principle) |
| 9 | Forged passages (C-4) | Fixed: NFKC folding, opening and closing tags neutralised |
| 10 | Mode survives LLM change (B-2) | Fixed |
| 11 | Super-admin sees integration settings via export (A-5, B-3) | Accepted and documented (needed to move a platform; never credentials) |
| 12 | Status page logins / Jira name (B-4) | Name removed; logins on load accepted (operator view, no customer content) |
| 13 | Disabled customer / lost customer (B-5, B-6) | Fixed for Test, Try a lookup and `#` changes; exports of a disabled customer kept on purpose (offboarding) |
| 14 | No rate limits (D-4) | Fixed: per-user limits; per-customer token budgets not yet |
| 15 | Credentials over HTTP (E-2) | Fixed: HTTPS only unless private addresses are allowed |
| 16 | Backups and key rotation (E-3) | Key rotation added; encrypted backups remain an operator choice (documented) |
| 17 | Unpinned build backend (E-4) | Fixed |
| 18 | Any package can register a connector (E-5) | Fixed |
| 19 | No rollback in release note (E-7) | Fixed in the v0.4.1 release note |
| 20 | Links survive as text (C-5) | Fixed for brackets, `www.`, `//host` |
| 21 | Hidden draft title, unchecked follow-ups (C-6, C-7) | Title fixed; follow-ups and history accepted (questions only, no values) |
| 22 | Info items | Plugins context no longer in a layer (bind mount); proxies ignored; backslash links refused; others accepted |

Regression tests: `backend/tests/test_security_v040.py`, the authorization matrix, `tests/test_document_export.py`.

## Not covered by this review

Dynamic testing against a running stack; real vendor APIs (plugins verified with mocks); the document parsers (worker) beyond the v0.3.2 review.
