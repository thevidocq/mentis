# Installing Mentis

> Version 0.2.0. Release notes and upgrade commands: [docs/releases/](docs/releases/).

## Requirements

- Linux host with Docker Engine and the Docker Compose plugin.
- At least 4 vCPU and 12 GB RAM (the embedding model alone uses about 3 GB); 16 GB recommended. About 10 GB of free disk for images and the model.
- The `worker` container (document processing) is limited to 2 CPUs and 3 GB RAM by default; change `MENTIS_WORKER_CPUS` / `MENTIS_WORKER_MEMORY` in `.env`.

## Install

```bash
git clone https://github.com/thevidocq/mentis.git
cd mentis
git checkout v0.2.0        # a release; main is the development version
cp .env.example .env
sed -i "s/^MENTIS_SECRET_KEY=.*/MENTIS_SECRET_KEY=$(openssl rand -hex 32)/" .env
for k in POSTGRES_PASSWORD MINIO_ROOT_PASSWORD QDRANT_API_KEY REDIS_PASSWORD; do
  sed -i "s/^$k=.*/$k=$(openssl rand -hex 24)/" .env
done
nano .env                  # MENTIS_PUBLIC_URL, and MENTIS_WEB_PORT if 8080 is taken
chmod 600 .env
docker compose up -d --build
docker compose logs -f embeddings    # first start downloads bge-m3 (~2.3 GB); Ctrl+C at "Ready"
./check.sh
```

Only the web interface is published, on `127.0.0.1:${MENTIS_WEB_PORT}` (8080 by default). The API, PostgreSQL, Qdrant, MinIO and Redis publish no host port. Database migrations run automatically every time the API container starts.

## Create the super-admin

On the server, from the Mentis folder:

```bash
docker compose exec api python -m app.cli create-admin
```

It asks for email, name and password (12+ characters, upper and lower case, a digit) and creates the General tenant too. It works only while no user exists. Then sign in: at the first login you scan a QR code with an authenticator app; 2FA is mandatory for everyone.

The browser setup page is off (`MENTIS_WEB_SETUP=false`), so whoever reaches a fresh public address first cannot claim the platform. Set it to `true` only on a lab reachable through an SSH tunnel.

Next steps in the interface:
1. **Email (SMTP)**: so invitations are emailed. Without it, the invitation link is shown to you to share. `MENTIS_PUBLIC_URL` must be the address users open.
2. **Tenants**: onboard each customer.
3. **AI providers**: add the LLM that writes the answers (preset **Claude Haiku**: paste the Anthropic API key) and click **Test**.
4. **Users**: invite tenant admins (one or more customers each) and analysts (all customers).

## Publish it with HTTPS

Put a reverse proxy with HTTPS in front of the web port. Two common cases:

### Behind the Caddy of Equalizer (same VPS)

Equalizer's Caddy already holds ports 80 and 443. Join Mentis to its network and add one site to its Caddyfile; Caddy gets the certificate.

```bash
cd ~/mentis
cat > docker-compose.override.yml <<'YML'
services:
  web:
    networks:
      default: {}
      edge:
        aliases: [mentis-web]
networks:
  edge:
    external: true
    name: equalizer_edge
YML
docker compose up -d web

cd ~/equalizer/deploy/compose
cat >> caddy/Caddyfile <<'CADDY'

mentis.example.com {
	encode zstd gzip
	request_body {
		max_size 60MB
	}
	reverse_proxy mentis-web:8080
}
CADDY
docker compose restart caddy
```

`docker-compose.override.yml` is not part of the repository, so Mentis upgrades keep it. The DNS record must point to the VPS; with Cloudflare, set it to *DNS only* so Caddy can obtain the certificate.

### Your own nginx

```nginx
server {
    listen 443 ssl;
    server_name mentis.example.com;
    # ssl_certificate / ssl_certificate_key ...
    client_max_body_size 60m;

    location / {
        proxy_pass http://127.0.0.1:8080;     # MENTIS_WEB_PORT
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
    }
}
```

The real client IP in Logs comes from `X-Forwarded-For`, trusted only from private networks (`MENTIS_TRUSTED_PROXIES`).

Browsers accept the secure session cookie on `http://127.0.0.1` and `http://localhost`. Over plain HTTP from another host name, sign-in does not stick unless `MENTIS_COOKIE_SECURE=false` (tests only).

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

If you edited `docker-compose.yml` or `check.sh` by hand, `git checkout` refuses to switch: put your change in `.env` or `docker-compose.override.yml` instead, then `git checkout -- docker-compose.yml check.sh`.

## Operator commands

```bash
# First super-admin (only while no user exists)
docker compose exec api python -m app.cli create-admin
# User lost the authenticator: remove 2FA, they enroll again at next login
docker compose exec api python -m app.cli reset-2fa user@example.com
# Clear a login lockout (5 failed attempts lock the account for 15 minutes)
docker compose exec api python -m app.cli unlock user@example.com
```
