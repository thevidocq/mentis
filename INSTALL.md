# Installing Mentis

> Version 0.1.0. Release notes and upgrade commands: [docs/releases/](docs/releases/).

## Requirements

- Linux host with Docker Engine and the Docker Compose plugin.
- At least 4 vCPU and 12 GB RAM (the embedding model alone uses about 3 GB); 16 GB recommended. About 10 GB of free disk for images and the model.
- The `worker` container (document processing) is limited to 2 CPUs and 3 GB RAM by default; change `MENTIS_WORKER_CPUS` / `MENTIS_WORKER_MEMORY` in `.env`.

## Install

```bash
git clone https://github.com/thevidocq/mentis.git
cd mentis
git checkout v0.1.1        # a release; main is the development version
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
3. **AI providers**: add the LLM that writes the answers (preset **Claude Haiku**: paste the Anthropic API key) and click **Test**. Without a provider the chat answers with an error.
4. **Users**: invite tenant admins (one customer each) and analysts (all customers).

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

Embeddings: the `embeddings` container runs BAAI/bge-m3 (Hugging Face TEI, CPU). **On first start it downloads the model (about 2.3 GB)**; until then the Embeddings line on Service status is Down and uploads fail with "Indexing failed" (use Retry afterwards). Follow it with `docker compose logs -f embeddings`. Limits: `MENTIS_EMBEDDINGS_CPUS` / `MENTIS_EMBEDDINGS_MEMORY`.

More workers in parallel: `MENTIS_WORKER_REPLICAS=3` in `.env`, then `docker compose up -d`.

Parser: `MENTIS_PARSER=standard` (default). To try Docling in the lab, set `MENTIS_PARSER=docling` and `MENTIS_PARSER_EXTRAS=worker,docling` in `.env`, then `docker compose up -d --build worker` (large download: PyTorch and models).

## Chat and LLM

The `api` container calls the LLM providers configured in **AI providers**. It needs outbound HTTPS to cloud providers (`api.anthropic.com`, `api.openai.com`). For a model server on the same host (Ollama, vLLM), use `http://host.docker.internal:<port>/v1` as Base URL; for one in another compose project, put it on a shared Docker network and use its service name.

Retrieval tuning in `.env`: `MENTIS_CHAT_PASSAGES` (default 8) and `MENTIS_CHAT_MIN_SCORE` (default 0.3), then `docker compose up -d api`.

## Backup

```bash
./backup.sh                                   # backups/mentis-<date>/ (database, documents, index, .env)
./restore.sh backups/mentis-<date>            # same server
./restore.sh backups/mentis-<date> --with-env # new server
```

Backups contain `.env` with every secret: keep them encrypted and off the server. Nightly cron example and details: [Backup and configuration](frontend/src/help/super-admin/12-backup-configuration.md).

## Upgrade

```bash
cd mentis
./backup.sh
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
