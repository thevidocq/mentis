# Backend

FastAPI API and core services. See `docs/DESIGN.md` for scope.

## Layout

```
app/
  core/       settings, database, password/TOTP/session security, secret encryption
  models/     SQLAlchemy models (tenants, users, auth sessions, log events, invitations, platform settings)
  services/   business logic (sessions, logs, tenants, users rules, invitations, mail)
  api/        dependencies, schemas, routes (health, setup, auth, tenants, users, invitations, platform)
  ingestion/  parsing (standard: pdfplumber/pypdfium2/Tesseract/python-docx/python-pptx/openpyxl; optional Docling), chunking
  worker/     RQ worker entry point and the ingestion job (python -m app.worker)
  cli.py      operator commands (reset-2fa, unlock)
migrations/   Alembic migrations (run automatically at container start)
tests/        pytest suite (SQLite in memory)
```

## Development

```bash
cd backend
pip install -e ".[dev,worker]"   # plus the tesseract-ocr binary for OCR tests
pytest
MENTIS_COOKIE_SECURE=false uvicorn app.main:app --reload   # SQLite file by default
```

New migration after changing models:

```bash
alembic revision --autogenerate -m "describe change"
```

## API conventions

- Every state-changing request (`POST`, `PUT`, `PATCH`, `DELETE`) must send the header `X-Mentis-Request: 1` (CSRF protection).
- Sessions are server-side; the browser holds an `HttpOnly`, `SameSite=Strict` cookie.
- Login is two steps: `POST /api/auth/login` returns a short-lived challenge, then `POST /api/auth/totp/verify` (after `/totp/enroll` on first login) opens the session.
