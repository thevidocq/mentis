# Changelog

All notable changes to this project are documented here. Every commit updates this file so that work can be resumed from any session.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- Project design document (`docs/DESIGN.md`).
- Logo assets (`assets/logo/`): light and dark wordmark, standalone icon.
- Repository layout: `backend/`, `frontend/`, `plugins/`.
- Draft `docker-compose.yml` with infrastructure services (PostgreSQL, Qdrant, MinIO, Redis) and `.env.example`.
- Draft `INSTALL.md`.
- `CLAUDE.md` with project conventions for development sessions.

### Changed
- Design: MVP scope extended with first-run setup, SMTP invites, answer feedback, LLM usage per tenant, single Logs section with syslog forwarding, backup/restore, configuration import/export.
