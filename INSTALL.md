# Installing Mentis

> Work in progress. Available now: API with first-run setup and login (password + mandatory TOTP 2FA), plus the infrastructure services. Frontend, ingestion worker and embeddings come later in 0.1.0.

## Requirements

- Linux host with Docker Engine and the Docker Compose plugin.
- At least 4 vCPU and 8 GB RAM; 16 GB recommended once documents are ingested (OCR and local embeddings are CPU- and RAM-heavy).

## Install

```bash
git clone https://github.com/thevidocq/mentis.git
cd mentis
cp .env.example .env
# Set every CHANGE_ME. For MENTIS_SECRET_KEY:  openssl rand -hex 32
nano .env
docker compose up -d --build
./check.sh
```

All ports bind to `127.0.0.1` only. The API listens on `127.0.0.1:8000`; publish it through a reverse proxy (nginx) with HTTPS.

Database migrations run automatically every time the API container starts.

## First-run setup

Until the frontend ships, run the setup once through the API (interactive docs at `http://127.0.0.1:8000/api/docs`):

```bash
curl -X POST http://127.0.0.1:8000/api/setup \
  -H 'Content-Type: application/json' -H 'X-Mentis-Request: 1' \
  -d '{"email":"you@example.com","full_name":"Your Name","password":"A-Strong-Password-1"}'
```

This creates the General tenant and the super-admin. It works only once. Other users are invited from the platform (`POST /api/invitations`); configure SMTP first (`PUT /api/platform/smtp`), otherwise the API returns the invitation link for you to share manually. Set `MENTIS_PUBLIC_URL` in `.env` so links point to the right address. At the first login the user must set up an authenticator app (TOTP); 2FA is mandatory for everyone.

Passwords: at least 12 characters, upper and lower case, at least one digit.

## Reverse proxy (nginx example)

```nginx
server {
    listen 443 ssl;
    server_name mentis.example.com;   # or localhost
    # ssl_certificate / ssl_certificate_key ...

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Testing over plain `http://localhost` without TLS: set `MENTIS_COOKIE_SECURE=false` in `.env`, otherwise the browser will not keep the session cookie.

## Upgrade

```bash
cd mentis
git fetch --tags
git checkout <version-tag>
docker compose up -d --build
./check.sh
```

## Operator commands

```bash
# User lost the authenticator: remove 2FA, they enroll again at next login
docker compose exec api python -m app.cli reset-2fa user@example.com
# Clear a login lockout (5 failed attempts lock the account for 15 minutes)
docker compose exec api python -m app.cli unlock user@example.com
```
