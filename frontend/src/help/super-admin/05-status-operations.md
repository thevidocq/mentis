# Service status and operations

## Service status

Shows each service with its state, latency and detail, refreshed every 60 seconds. Right now it covers the API and the database; Qdrant, MinIO, workers, embeddings, LLM providers and integrations are added as they ship.

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
