#!/usr/bin/env bash
# Full backup of Mentis: PostgreSQL, documents (MinIO), vector index (Qdrant) and .env.
# Run from the installation folder:  ./backup.sh [destination-folder]
# Default destination: backups/mentis-<date>. Keep backups off the server: they contain .env (secrets).
set -euo pipefail
cd "$(dirname "$0")"

DEST="${1:-backups/mentis-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$DEST"
chmod 700 "$DEST"
DEST="$(cd "$DEST" && pwd)"

container() { docker compose ps -aq "$1" | head -1; }
API_IMAGE=$(docker inspect -f '{{.Image}}' "$(container api)")
# Copy a service's data folder with a throwaway container that mounts the same volume.
archive() {  # service, path in the container, output file
  docker run --rm --user 0 --entrypoint tar --volumes-from "$(container "$1")" -v "$DEST":/backup "$API_IMAGE" \
    czf "/backup/$3" -C "$2" .
}

echo "Backing up to $DEST"

echo "- PostgreSQL"
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' | gzip > "$DEST/postgres.sql.gz"

echo "- Documents (MinIO)"
archive minio /data minio.tar.gz

echo "- Vector index (Qdrant, paused for a few seconds)"
docker compose pause qdrant >/dev/null
trap 'docker compose unpause qdrant >/dev/null 2>&1 || true' EXIT
archive qdrant /qdrant/storage qdrant.tar.gz
docker compose unpause qdrant >/dev/null
trap - EXIT

echo "- Settings (.env)"
install -m 600 .env "$DEST/env.backup"

{
  echo "created=$(date -Iseconds)"
  echo "version=$(git describe --tags --always 2>/dev/null || echo unknown)"
  echo "host=$(hostname)"
} > "$DEST/manifest.txt"
(cd "$DEST" && sha256sum postgres.sql.gz minio.tar.gz qdrant.tar.gz env.backup > SHA256SUMS)

du -sh "$DEST" | awk '{print "Done: " $2 " (" $1 ")"}'
