#!/usr/bin/env bash
# Restore a backup made by backup.sh. Replaces ALL current data: database, documents and vector index.
# Run from the installation folder:  ./restore.sh backups/mentis-<date>[.tar.gpg] [--with-env]
#   --with-env  also restore .env (needed on a new server: the secret key decrypts stored passwords and keys)
# An encrypted backup (.tar.gpg) is decrypted next to it first: with MENTIS_BACKUP_PASSPHRASE_FILE
# (environment or .env) for a passphrase, otherwise gpg asks for the passphrase or private key.
set -euo pipefail
cd "$(dirname "$0")"
umask 077

SRC="${1:?Usage: ./restore.sh <backup-folder or .tar.gpg> [--with-env]}"
WITH_ENV="${2:-}"
if [ -f "$SRC" ]; then
  case "$SRC" in *.gpg) ;; *) echo "Not a backup folder or a .tar.gpg file: $SRC"; exit 1 ;; esac
  command -v gpg >/dev/null || { echo "gpg is needed to decrypt $SRC (apt install gnupg)."; exit 1; }
  setting() {
    local v="${!1:-}"
    if [ -z "$v" ] && [ -f .env ]; then v="$(grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d "\"'\r" || true)"; fi
    printf '%s' "$v"
  }
  PASSPHRASE_FILE="$(setting MENTIS_BACKUP_PASSPHRASE_FILE)"
  WORK="$(mktemp -d "$(dirname "$SRC")/.restore-XXXXXX")"
  trap 'rm -rf "$WORK"' EXIT
  echo "Decrypting $SRC"
  if [ -n "$PASSPHRASE_FILE" ]; then
    gpg --batch --pinentry-mode loopback --passphrase-file "$PASSPHRASE_FILE" --decrypt "$SRC"
  else
    gpg --decrypt "$SRC"
  fi | tar -C "$WORK" -xf -
  SRC="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -1)"
  [ -n "$SRC" ] || { echo "The archive does not contain a backup folder."; exit 1; }
fi
SRC="$(cd "$SRC" && pwd)"
for f in postgres.sql.gz minio.tar.gz qdrant.tar.gz env.backup; do
  [ -f "$SRC/$f" ] || { echo "Missing $SRC/$f"; exit 1; }
done
(cd "$SRC" && sha256sum -c --quiet SHA256SUMS) || { echo "Checksum mismatch: the backup is damaged."; exit 1; }
cat "$SRC/manifest.txt"

key() { [ -f "$1" ] && grep -E '^MENTIS_SECRET_KEY=' "$1" | cut -d= -f2-; }
if [ "$WITH_ENV" != "--with-env" ] && [ "$(key .env)" != "$(key "$SRC/env.backup")" ]; then
  echo "WARNING: MENTIS_SECRET_KEY in .env differs from the backup. Stored passwords and API keys will not decrypt."
  echo "Run again with --with-env to restore the backup's .env, or press Ctrl+C."
fi

echo
echo "This REPLACES all current data of this installation with the backup."
read -r -p "Type RESTORE to continue: " answer
[ "$answer" = "RESTORE" ] || { echo "Cancelled."; exit 1; }

# Only after the confirmation: a cancelled restore must leave .env as it was.
if [ "$WITH_ENV" = "--with-env" ]; then
  [ -f .env ] && cp .env ".env.before-restore.$(date +%s)"
  install -m 600 "$SRC/env.backup" .env
  echo ".env restored (previous one saved as .env.before-restore.*)."
fi

container() { docker compose ps -aq "$1" | head -1; }
# Create every container (building images if missing, e.g. on a new server): the api image is used below.
docker compose up --no-start >/dev/null
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
# The database role keeps the password it was created with; make it match POSTGRES_PASSWORD of the
# current .env (it differs when --with-env brought the backup's .env onto an existing installation).
docker compose exec -T postgres sh -c 'psql -q -v ON_ERROR_STOP=1 -v pw="$POSTGRES_PASSWORD" -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null <<'SQL'
ALTER ROLE CURRENT_USER PASSWORD :'pw';
SQL

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
