# Installing Mentis

> Version 0.3.7. Release notes and upgrade commands: [docs/releases/](docs/releases/).

## Requirements

- Linux host with Docker Engine and the Docker Compose plugin, version 2.17 or later (`docker compose version`): the api image is built with a second build context for the integration plugins.
- At least 4 vCPU and 12 GB RAM (the embedding model alone uses about 3 GB); 16 GB recommended. About 10 GB of free disk for images and the model.
- The `worker` container (document processing) is limited to 2 CPUs and 3 GB RAM by default; change `MENTIS_WORKER_CPUS` / `MENTIS_WORKER_MEMORY` in `.env`.

## Install

```bash
git clone https://github.com/thevidocq/mentis.git
cd mentis
git checkout v0.3.7        # a release; main is the development version
cp .env.example .env
chmod 600 .env             # secrets: readable by the owner only
sed -i "s/^MENTIS_SECRET_KEY=.*/MENTIS_SECRET_KEY=$(openssl rand -hex 32)/" .env
for k in POSTGRES_PASSWORD MINIO_ROOT_PASSWORD QDRANT_API_KEY REDIS_PASSWORD; do
  sed -i "s/^$k=.*/$k=$(openssl rand -hex 24)/" .env
done
nano .env                  # MENTIS_PUBLIC_URL, and MENTIS_WEB_PORT if 8080 is taken
docker compose up -d --build
docker compose logs -f embeddings    # first start downloads bge-m3 (~2.3 GB); Ctrl+C at "Ready"
./check.sh
```

Only the web interface is published, on `127.0.0.1:${MENTIS_WEB_PORT}` (8080 by default). The API, PostgreSQL, Qdrant, MinIO and Redis publish no host port. Database migrations run automatically every time the API container starts.

The API refuses to start while a secret is missing or still a `CHANGE_ME` placeholder (`MENTIS_SECRET_KEY`, `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `QDRANT_API_KEY`, `REDIS_PASSWORD`); `docker compose` itself stops with "required variable ... is missing a value" when one is empty. Qdrant never runs without its API key.

### Isolation

- **Networks.** PostgreSQL, Qdrant, MinIO, Redis and the embeddings container are on an internal network (`mentis_data`, no outbound traffic) shared only with `api` and `worker`. The `web` container is not on it, so a network it joins (for example `equalizer_edge`) cannot reach the data stores. The embeddings container also has its own network to download the model.
- **Containers.** Every container runs with `no-new-privileges` and without Linux capabilities (the data stores keep only those their entrypoint needs). `web` (nginx, uid 101), `api` and `worker` (uid 10001) run as non-root on a read-only filesystem with `/tmp` in memory (`MENTIS_WEB_TMP_SIZE` 512m, `MENTIS_API_TMP_SIZE` 512m, `MENTIS_WORKER_TMP_SIZE` 1g: raise them if very large uploads or OCR jobs fail with "No space left on device").
- **Images** have fixed versions (Qdrant `v1.20.0`, Redis `7.4`, PostgreSQL `16`, nginx `1.30`). To pick up security fixes of the base images: `docker compose build --pull && docker compose pull --ignore-buildable && docker compose up -d`.
- **Request size.** The web container accepts bodies up to 10 MB, 100 MB only for document uploads.

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
3. **AI providers**: add the LLM that writes the answers (for example preset **Anthropic**: paste the API key, **Load models**, pick one) and click **Test**.
4. **Users**: invite tenant admins and analysts, ticking their customers (or **All customers, including future ones**). Give **General** to at least one tenant admin: General documents are managed by tenant admins, not by the super-admin.

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
        proxy_read_timeout 300s;     # as long as the web container waits for the API
    }
}
```

The real client IP in Logs comes from `X-Forwarded-For`, trusted only from private networks (`MENTIS_TRUSTED_PROXIES`). When users reach Mentis from a private network (office LAN, VPN), set `MENTIS_TRUSTED_PROXIES` to the addresses of your proxies only (for example `127.0.0.1,172.16.0.0/12` for the web container and a proxy on this host): otherwise a client on that network can put any address in `X-Forwarded-For`, and it is believed for the Logs and the sign-in rate limit.

Sign-in, 2FA, password reset, invitation and setup requests are limited per client IP: `MENTIS_AUTH_RATE_PER_MINUTE` (default 30; `0` turns the limit off). Above it the API answers 429 for a minute. Raise it if many users sign in through one NAT address at the same moment.

Browsers accept the secure session cookie on `http://127.0.0.1` and `http://localhost`. Over plain HTTP from another host name, sign-in does not stick unless `MENTIS_COOKIE_SECURE=false` (tests only).

## Document processing

Uploaded documents are processed by the `worker` container. If uploads stay **Queued**, check it:

```bash
docker compose ps worker
docker compose logs -f worker
```

Embeddings: the `embeddings` container runs BAAI/bge-m3 (Hugging Face TEI, CPU). **On first start it downloads the model (about 2.3 GB)**; until then the Embeddings line on Service status is Down and uploads fail with "Indexing failed" (use Retry afterwards). Follow it with `docker compose logs -f embeddings`. Limits: `MENTIS_EMBEDDINGS_CPUS` / `MENTIS_EMBEDDINGS_MEMORY`. RAM: plan at least 8 GB for the whole host; with less, add swap and set `MENTIS_EMBEDDING_BATCH_SIZE=4` (texts per request), or uploads fail with "The document search service is not available" when the embedding service runs out of memory and restarts.

More workers in parallel: `MENTIS_WORKER_REPLICAS=3` in `.env`, then `docker compose up -d`.

Parser: `MENTIS_PARSER=standard` (default). To try Docling in the lab, set `MENTIS_PARSER=docling` and `MENTIS_PARSER_EXTRAS=worker,docling` in `.env`, then `docker compose up -d --build worker` (large download: PyTorch and models).

## Chat and LLM

The `api` container calls the LLM providers configured in **AI providers**. It needs outbound HTTPS to cloud providers (`api.anthropic.com`, `api.openai.com`). For a model server on the same host (Ollama, vLLM), use `http://host.docker.internal:<port>/v1` as Base URL; for one in another compose project, put it on a shared Docker network and use its service name.

Retrieval tuning in `.env`: `MENTIS_CHAT_PASSAGES` (default 8) and `MENTIS_CHAT_MIN_SCORE` (default 0.3), then `docker compose up -d api`.

## Integrations

The integration plugins in `plugins/` (ServiceNow, Jira, CrowdStrike, Microsoft Defender, Trend Vision One) are installed into the `api` image at build time. They are off until a super-admin enables them in **Integrations**; tenant admins then configure them for their customers.

The `api` container needs outbound HTTPS to each customer's systems: the ServiceNow instance or Jira site (on-premise Jira Data Center may need a route or VPN from the VPS), `api.crowdstrike.com` (or the customer's region), `login.microsoftonline.com` and `api*.securitycenter.microsoft.com`, `api*.xdr.trendmicro.com`. Customers that restrict API access by source IP must allow the VPS's public address.

Check what is installed:

```bash
docker compose exec api python -c "from app.connectors import registry; print(sorted(registry.connectors()))"
```

Plugin tests run from a checkout, without services: `python -m pytest plugins/` (Python 3.12 and pytest).

## Backup

```bash
./backup.sh                                   # backups/mentis-<date>/ (database, documents, index, .env)
./restore.sh backups/mentis-<date>            # same server
./restore.sh backups/mentis-<date> --with-env # new server
```

Backups contain `.env` with every secret: keep them encrypted and off the server. The backup folder and its files are readable by the owner only. Nightly cron example and details: [Backup and configuration](frontend/src/help/super-admin/12-backup-configuration.md).

Encrypted backups (needs `gpg`, `apt install gnupg`): set one of these in `.env`, and `./backup.sh` writes `backups/mentis-<date>.tar.gpg` and removes the unencrypted folder.

```bash
# Public key (recommended: the server cannot read its own backups). Import the public key first:
gpg --import backup-public.asc
echo "MENTIS_BACKUP_GPG_RECIPIENT=backup@example.com" >> .env
# Or a passphrase file:
( umask 077; openssl rand -base64 32 > /root/.mentis-backup-pass )
echo "MENTIS_BACKUP_PASSPHRASE_FILE=/root/.mentis-backup-pass" >> .env

./restore.sh backups/mentis-<date>.tar.gpg    # decrypts, then restores as usual
```

Keep a copy of the passphrase or private key off the server: without it the backups cannot be restored.

Rotation: `./backup.sh` keeps the newest 7 complete backups in `backups/` (`MENTIS_BACKUP_KEEP`, 0 = all), refuses to start without enough free space, and removes a backup that failed half-way. Backups on the same disk do not survive a disk failure: copy them elsewhere.

## Storage over time

Where the space goes, and what keeps it in check:

| What | Where | Grows with | Kept in check by |
| --- | --- | --- | --- |
| Original files, page images | MinIO volume | every version uploaded | deleting documents; **Retention → Old document versions** |
| Extracted text, passages, chats, logs | PostgreSQL volume | versions, questions, events | the same, plus chat and log retention |
| Vector index | Qdrant volume (vectors on disk, graph in RAM) | passages of every version | the same |
| Container logs | Docker | time | rotation: 5 × 20 MB per container (`MENTIS_LOG_MAX_SIZE`, `MENTIS_LOG_MAX_FILES`) |
| Images and build cache | Docker | every upgrade | `docker image prune -f && docker builder prune -f` after an upgrade |
| Backups | `backups/` | every backup | rotation (`MENTIS_BACKUP_KEEP`) |

`./check.sh` shows free disk space (warning at 80%, failure at 90%), the size of each volume (with `sudo`), backups and reclaimable Docker space. A daily sweep removes files and index entries left behind when MinIO or Qdrant were down during a deletion. Page images are WebP (about a quarter of a PNG). Plan the disk at roughly 3–4 times the size of the original files you will upload (originals, page images, text, index, one backup), plus 10 GB for images and the embedding model.

## Upgrade

```bash
cd mentis
./backup.sh
git fetch --tags
git checkout <version-tag>
docker compose up -d --build
./check.sh
docker image prune -f && docker builder prune -f   # space left by the previous version's images
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
