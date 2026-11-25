# Changelog

All notable changes to this project are documented here. Every commit updates this file so that work can be resumed from any session.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
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
- Backend test suite (13 tests).

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
