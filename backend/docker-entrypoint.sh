#!/bin/sh
set -e
# Apply database migrations on every start, then serve the API.
alembic upgrade head
# --proxy-headers: trust X-Forwarded-* from the reverse proxy (nginx) for client IPs.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="${MENTIS_TRUSTED_PROXIES:-127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}"
