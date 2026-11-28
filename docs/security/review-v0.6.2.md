# Security and accuracy review v0.6.2

Five parallel reviews of v0.6.2 (ingestion; embedding, index and retrieval; LLM answer path; answer check; authentication, authorization and API surface), each finding reproduced with a runnable proof, plus a triage of the failing test suite. The test environment had no Docker daemon: everything ran in-process (SQLite, in-memory Qdrant, fake embeddings and LLM), and level-2 bypasses were measured with an "oracle" checker that rejects every wrong statement it is shown. Fixed in the next release unless marked otherwise; each fix has a regression test (`tests/test_check_coverage.py`, `test_ingestion_limits.py`, `test_retrieval_review.py`, `test_llm_review.py`).

## Fixed

| ID | Severity | Finding | Fix |
|---|---|---|---|
| C-1 | Critical | **Code blocks were never checked**: commands, IPs and hashes in them reached the analyst with "Matches the sources". | Every code block is a unit at both levels, against its lead line's passages (else the answer's). |
| C-2 | Critical | The check and the chat disagreed on what a code block is: a "~~~" or indented fence was skipped by the check but shown as prose, so cited text with a wrong phone passed. | The check recognises blocks exactly as the chat renders them (three backticks at the start of a line; a table row starts and ends with "\|"). |
| C-3 | High | Table rows never reached level 2; an answer made only of a table got the badge with nothing checked. | Each row is a unit (header row an introduction); "Matches the sources" needs the checker to have read at least one statement. |
| C-4 | High | `#` headings without a citation were dropped by both levels. | Checked like bold headings (values against their items' passages; level 2 as an introduction). |
| C-5 | High | Short uncited orders ("Isolate the domain controllers."), lines ending with ":" that head nothing, bold lines, uncited sentences after a citation and "\| text" without a closing pipe passed unchecked. | Every unit reaches level 2; uncited ones are marked "(no citation)" and pass only if they state no fact; an intro is only a line that really heads items. |
| C-6 | Medium | A level-2 rejection was dropped when any level-1 value matched inside it, even of another statement. | Issues are joined only within the same statement. |
| C-7 | Medium | Verdicts in other shapes ("statement": 2, lists, "S1-S3") were read as "supported". | All these forms are read; a rejection without a readable number makes the check unavailable. |
| C-8 | Medium | The checker read the text with `_`, `*` and backticks removed ("svcbackup" for "svc_backup"). | Only paired Markdown markers are removed; statements are sent as data. |
| C-9 | Medium | Level 1 missed SOC values: phones in 3-3-3 groups (read as amounts), an invented country code, defanged IOCs, near-hash hex runs, SHA-512, MAC, domains, URLs, paths, registry keys, event IDs, ports, counts, "2h30", "fifteen minutes", range bounds, "8 PM". | Extracted and compared (`values.py`); bold no longer splits a number. |
| C-10 | Low | False positives: "90 minutes" or "1.5 hours" against "1 hour 30 minutes"; a phone with bold digits. | Compound durations summed; text read without paired markers. |
| C-11 | High | (Second round.) Paragraph and ">" lines were checked one by one while the chat joins them: "Do not⏎isolate…" passed as two harmless pieces. | Units are built as the chat builds blocks. |
| C-12 | High | (Second round.) Bidi override characters were removed by both checks but kept in the answer: the browser could show "2233" as "3322". | Invisible format characters are removed from the answer itself. |
| C-13 | Medium | (Second round.) One-character units ("- 3", "\| 3 \|") were dropped; a table header and its rows could be judged in different checker calls. | Any unit with a letter or digit is checked; rows carry their column names; an introduction never ends a checker call. |
| C-14 | Medium | (Second round.) In hide mode, statements beyond the 24 checked were shown. | Counted as a failure: rewritten shorter, else hidden. |
| C-15 | Low | (Second round.) "_x_" was checked without its underscores, which the chat shows; "1½ hours", "21h", "9-11 PM", a bare event ID were false positives. | Fixed. |
| D-1 | Medium | (Docs audit.) `MENTIS_PARSE_*`, `MENTIS_OCR_TIMEOUT_SECONDS` and `MENTIS_EMBEDDING_ALLOWED_URLS` set in `.env` never reached the containers. | Passed by `docker-compose.yml`, listed in `.env.example`. |
| I-1 | High | Chunking was quadratic (code blocks, every YAML document, long runs of spaces) and ran in the worker outside the reader's limits: a 24 KB file held the shared worker 30 s, about 200 KB the whole 30-minute job. | Linear algorithms; chunking runs in the limited child process. |
| I-2 | Low | A job timeout left Tesseract processes running and was reported as "The file could not be read". | The child has its own process group, killed whole; the timeout propagates; OCR per picture limited (`MENTIS_OCR_TIMEOUT_SECONDS`). |
| I-3 | Low | The uploader of a General Knowledge Base version could approve it. | Setting **Approval by another person** (off by default); self-approval logged as a warning. |
| R-1 | Medium | A document deleted while an answer was written stayed in that answer for ever. | Answers are checked on every read against existing documents and versions, and the save re-checks. |
| R-2 | Medium | The background level-2 check wrote over a removed answer, bringing back quotes of it. | The message is read again, locked, and never written once removed. |
| R-3 | Medium | The stored embedding API key (and the SMTP password, and the `.env` embedding key) followed a change of address, in the panel and through an import. | Moving to a new address without a new secret drops the stored one, in the panel and on import. |
| R-4 | Medium | A reindex failing while clearing the index resumed answers from a half-empty index. | Answers stay paused from the first deletion. |
| R-5 | Low | Uncited passages and follow-ups of a deleted document survived in answers. | Answers record every document they read (`read_documents`, migration 0016). |
| R-6 | Low | Model-written chat titles could quote a passage and were never hidden. | Chats are titled with the first question. |
| R-7 | Low | A reprocess whose old points could not be removed reported the wrong state; the dead points took places in searches. | Retried and reported apart; the daily sweep removes points of ready versions whose chunk is gone. |
| R-8 | Low | Embedding answers were not validated (NaN, mixed sizes, duplicate indices, unbounded body). | Validated; 64 MB cap; 8192 dimensions at most. |
| L-1 | Medium | "Nothing found for …" notes carried model-chosen search text (steerable by a ticket) under the answer, past the link filter and the check. | Only pattern-checked identifiers are named. |
| L-2 | Low | Invisible format characters hid passage tags from the neutraliser. | All format characters are removed from untrusted text before the tag check. |
| L-3 | Low | The hide-mode rewrite quoted the rejected draft raw after the question. | Quoted as data, neutralised. |
| L-4 | Low | Unknown addresses survived as text in link labels, in fullwidth, as `https:/x` or `host/path`. | Removed. |
| L-5 | Low | A lone surrogate in the model's reply lost the answer with an error blaming the question. | Replaced before storing. |
| T-1 | Info | 28 tests failed in a fresh environment since 0.4.1 (mock answers already read when built; stale tests; PyYAML 6.0.4 message); one was a real effect: a chunk's own heading embedded twice (0.6.1). | Mocks stream like a real server; heading embedded once (run **Reprocess all documents**). |

## Accepted

- **The super-admin can read every customer's documents through the embedding service** (point it at an address of their own and reindex). The move now drops the stored key and is logged as a warning; to remove the possibility, pin the addresses in `MENTIS_EMBEDDING_ALLOWED_URLS`. Same trust level as the accepted account takeover of v0.6.1.
- PT-07 (trusted proxies default to private ranges), first-login 2FA enrolment by whoever knows the password: unchanged, documented.

## Held up

Authorization matrix (105 routes × 9 actor classes × cross-tenant ids), 51 IDOR attempts on chats, documents and versions, setup, login and TOTP (replay, brute force, enrolment), sessions, password reset, CSRF, secrets (write-only, not exported), nginx and Compose hardening, backup and restore scripts, SSRF guard (every IPv4/IPv6 form tried), tenant isolation of uploads, storage keys and retrieval, stale or forged index entries, frontend rendering (no XSS; only cited record links clickable), tools-mode guards.

## Not covered

Crafted-file bombs (OOXML zip bombs, XXE, billion laughs, PDF/OCR bombs) were reviewed in the code only; behaviour against server Qdrant and PostgreSQL (advisory locks, strict mode) was not run.
