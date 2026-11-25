# Service status and operations

## Service status

Shows each service with its state, latency and detail, refreshed every 60 seconds: API, PostgreSQL, MinIO (stored documents), Redis (job queue, with the number of waiting jobs), the ingestion worker, Qdrant (vector index) and the embedding service. If the worker is **Down**, uploads stay **Queued** until it is back. If embeddings are **Down**, new versions fail with "Indexing failed" and can be retried. Each AI provider has its own line (**LLM: name**): the check lists the provider's models, so it verifies address and API key without spending tokens. **AI provider: Down** means none is configured. Integrations are added as they ship.

## Commands on the server

Run these from the Mentis folder on the server.

Check that everything is up (after install or upgrade):

```
./check.sh
```

Reset a user's 2FA or unlock an account without the interface:

```
docker compose exec api python -m app.cli reset-2fa user@example.com
docker compose exec api python -m app.cli unlock user@example.com
```

Upgrade to a new version:

```
git fetch --tags
git checkout <version-tag>
docker compose up -d --build
./check.sh
```

Database changes are applied automatically when the API starts.

Follow the ingestion worker (document processing) live:

```
docker compose logs -f worker
```

## Scaling document processing

In `.env` on the server:

- **More documents in parallel**: `MENTIS_WORKER_REPLICAS=3` (each worker processes one document at a time)
- **Faster on large documents**: `MENTIS_WORKER_CPUS=4` and `MENTIS_WORKER_MEMORY=6g` (limits apply to each worker)

Then apply:

```
docker compose up -d
./check.sh
```
