#!/usr/bin/env bash
# Restore a backup made by backup.sh. Replaces ALL current data: database, documents and vector index.
# Run from the installation folder:  ./restore.sh backups/mentis-<date> [--with-env]
#   --with-env  also restore .env (needed on a new server: the secret key decrypts stored passwords and keys)
set -euo pipefail
cd "$(dirname "$0")"

SRC="${1:?Usage: ./restore.sh <backup-folder> [--with-env]}"
WITH_ENV="${2:-}"
SRC="$(cd "$SRC" && pwd)"
for f in postgres.sql.gz minio.tar.gz qdrant.tar.gz env.backup; do
  [ -f "$SRC/$f" ] || { echo "Missing $SRC/$f"; exit 1; }
done
(cd "$SRC" && sha256sum -c --quiet SHA256SUMS) || { echo "Checksum mismatch: the backup is damaged."; exit 1; }
cat "$SRC/manifest.txt"

key() { grep -E '^MENTIS_SECRET_KEY=' "$1" | cut -d= -f2-; }
if [ "$WITH_ENV" = "--with-env" ]; then
  [ -f .env ] && cp .env ".env.before-restore.$(date +%s)"
  install -m 600 "$SRC/env.backup" .env
  echo ".env restored (previous one saved as .env.before-restore.*)."
elif [ "$(key .env)" != "$(key "$SRC/env.backup")" ]; then
  echo "WARNING: MENTIS_SECRET_KEY in .env differs from the backup. Stored passwords and API keys will not decrypt."
  echo "Run again with --with-env to restore the backup's .env, or press Ctrl+C."
fi

echo
echo "This REPLACES all current data of this installation with the backup."
read -r -p "Type RESTORE to continue: " answer
[ "$answer" = "RESTORE" ] || { echo "Cancelled."; exit 1; }

container() { docker compose ps -aq "$1" | head -1; }
docker compose up -d postgres minio qdrant >/dev/null
API_IMAGE=$(docker inspect -f '{{.Image}}' "$(container api)")
unpack() {  # service, path in the container, archive
  docker run --rm --user 0 --entrypoint sh --volumes-from "$(container "$1")" -v "$SRC":/backup:ro "$API_IMAGE" \
    -c "find '$2' -mindepth 1 -delete && tar xzf '/backup/$3' -C '$2'"
}

echo "- Stopping the application"
docker compose stop web api worker >/dev/null

echo "- PostgreSQL"
until docker compose exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; do sleep 2; done
docker compose exec -T postgres sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
gunzip -c "$SRC/postgres.sql.gz" | docker compose exec -T postgres sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null

echo "- Documents (MinIO) and vector index (Qdrant)"
docker compose stop minio qdrant >/dev/null
unpack minio /data minio.tar.gz
unpack qdrant /qdrant/storage qdrant.tar.gz

echo "- Starting everything"
docker compose up -d >/dev/null
sleep 10
./check.sh || true
echo
echo "Restore done. If the backup comes from an older version, the database is migrated automatically at start."
