# Installing Mentis

> Work in progress. Available now: web interface with first-run setup, login (password + mandatory TOTP 2FA), tenants, users and invitations, SMTP, account settings, three themes, in-app Help, and document upload with versions, OCR and preview. Indexing (embeddings + Qdrant) and chat come next.

## Requirements

- Linux host with Docker Engine and the Docker Compose plugin.
- At least 4 vCPU and 8 GB RAM; 16 GB recommended once documents are ingested (OCR and local embeddings are CPU- and RAM-heavy).
- The `worker` container (document processing) is limited to 2 CPUs and 3 GB RAM by default; change `MENTIS_WORKER_CPUS` / `MENTIS_WORKER_MEMORY` in `.env`.

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

All ports bind to `127.0.0.1` only. Open the app at **http://127.0.0.1:8080** (the `web` container serves the interface and proxies `/api` to the API). For access from other machines, put your own nginx with HTTPS in front of port 8080.

Database migrations run automatically every time the API container starts.

## First-run setup

Open http://127.0.0.1:8080. The first visit shows the setup page: create the super-admin (this works only once; it also creates the General tenant). Then sign in: at the first login you scan a QR code with an authenticator app. 2FA is mandatory for everyone.

Passwords: at least 12 characters, upper and lower case, at least one digit.

Next steps in the interface:
1. **Email (SMTP)**: configure it so invitations are emailed. Without it, the invitation link is shown to you to share manually. Set `MENTIS_PUBLIC_URL` in `.env` to the address users open, so links point to the right place.
2. **Tenants**: onboard each customer.
3. **Users**: invite tenant admins (one customer each) and analysts (all customers).

## Reverse proxy (nginx example)

```nginx
server {
    listen 443 ssl;
    server_name mentis.example.com;   # or localhost
    # ssl_certificate / ssl_certificate_key ...

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Browsers accept the secure session cookie on `http://127.0.0.1` and `http://localhost`. If you reach the app over plain HTTP from another host name, set `MENTIS_COOKIE_SECURE=false` in `.env` (test only), otherwise sign-in will not stick.

## Document processing

Uploaded documents are processed by the `worker` container. If uploads stay **Queued**, check it:

```bash
docker compose ps worker
docker compose logs -f worker
```

Parser: `MENTIS_PARSER=standard` (default). To try Docling in the lab, set `MENTIS_PARSER=docling` and `MENTIS_PARSER_EXTRAS=worker,docling` in `.env`, then `docker compose up -d --build worker` (large download: PyTorch and models).

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
