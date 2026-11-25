# Changelog

All notable changes to this project are documented here. Every commit updates this file so that work can be resumed from any session.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
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
