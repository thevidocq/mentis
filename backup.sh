#!/usr/bin/env bash
# Full backup of Mentis: PostgreSQL, documents (MinIO), vector index (Qdrant) and .env.
# Run from the installation folder:  ./backup.sh [destination-folder]
# Default destination: backups/mentis-<date>. Keep backups off the server: they contain .env (secrets).
#
# Encryption (optional, with gpg): set one of these in .env or in the environment. The folder is then
# packed into backups/mentis-<date>.tar.gpg and the unencrypted copy is removed.
#   MENTIS_BACKUP_GPG_RECIPIENT=<key id or email>   public key: this server cannot decrypt its backups
#   MENTIS_BACKUP_PASSPHRASE_FILE=/root/.mentis-backup-pass   symmetric AES-256 with a passphrase file
#
# Rotation: with the default destination, only the newest MENTIS_BACKUP_KEEP complete backups (default 7)
# stay in backups/; 0 keeps them all. A backup that fails half-way is removed, so it never replaces a good one.
set -euo pipefail
cd "$(dirname "$0")"
# Every file written here is readable by the owner only.
umask 077

# Setting from the environment, else from .env (quotes and Windows line endings stripped).
setting() {
  local v="${!1:-}"
  if [ -z "$v" ] && [ -f .env ]; then v="$(grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d "\"'\r" || true)"; fi
  printf '%s' "$v"
}
GPG_RECIPIENT="$(setting MENTIS_BACKUP_GPG_RECIPIENT)"
PASSPHRASE_FILE="$(setting MENTIS_BACKUP_PASSPHRASE_FILE)"
if [ -n "$GPG_RECIPIENT$PASSPHRASE_FILE" ]; then
  command -v gpg >/dev/null || { echo "Backup encryption is configured but gpg is not installed (apt install gnupg)."; exit 1; }
  [ -z "$PASSPHRASE_FILE" ] || [ -r "$PASSPHRASE_FILE" ] || { echo "Cannot read MENTIS_BACKUP_PASSPHRASE_FILE=$PASSPHRASE_FILE"; exit 1; }
fi

KEEP="$(setting MENTIS_BACKUP_KEEP)"; KEEP="${KEEP:-7}"
DEFAULT_DEST=0; [ -z "${1:-}" ] && DEFAULT_DEST=1
DEST="${1:-backups/mentis-$(date +%Y%m%d-%H%M%S)}"
# A failed backup removes its folder: never write into a folder that already holds other files.
if [ -e "$DEST" ] && { [ ! -d "$DEST" ] || [ -n "$(ls -A "$DEST")" ]; }; then
  echo "$DEST already exists and is not an empty folder: choose a new destination."
  exit 1
fi
# The newest earlier backup, before this one's (empty) folder is created and becomes the newest.
last=$(ls -1dt backups/mentis-* 2>/dev/null | head -1 || true)
mkdir -p "$DEST"
chmod 700 "$DEST"
# Free space: a backup needs about as much as the data it copies (compressed, usually less).
avail_kb=$(df -Pk "$DEST" | awk 'NR==2 {print $4}')
need_kb=$([ -n "$last" ] && du -sk "$last" | awk '{print int($1 * 1.2)}' || echo 0)
if [ "${need_kb:-0}" -gt "${avail_kb:-0}" ]; then
  echo "Not enough free disk space for a backup: about $((need_kb / 1024)) MB needed, $((avail_kb / 1024)) MB free."
  rmdir "$DEST" 2>/dev/null || true
  exit 1
fi
complete=0
cleanup_partial() { [ "$complete" -eq 1 ] || { echo "Backup failed: removing the incomplete $DEST"; rm -rf "$DEST" "$DEST.tar.gpg"; }; }
trap cleanup_partial EXIT
DEST="$(cd "$DEST" && pwd)"

# The running container of a service; a stopped one only if none runs. A stopped leftover (an old
# one-off run) can point to an image that no longer exists: "No such image" in docker run.
container() { local id; id=$(docker compose ps -q "$1" | head -1); [ -n "$id" ] || id=$(docker compose ps -aq "$1" | head -1); echo "$id"; }
# By name (e.g. mentis-api): the image id of an old container may have been removed since.
API_IMAGE=$(docker inspect -f '{{.Config.Image}}' "$(container api)")
# Copy a service's data folder with a throwaway container that mounts the same volume.
archive() {  # service, path in the container, output file
  local rc=0
  docker run --rm --user 0 --entrypoint tar --volumes-from "$(container "$1")" -v "$DEST":/backup "$API_IMAGE" \
    --warning=no-file-changed -czf "/backup/$3" -C "$2" . || rc=$?
  # GNU tar exits 1 when a file changed while it was read (MinIO keeps running): the archive is
  # complete, so do not abort the whole backup for it. Any other code is a real failure.
  [ "$rc" -eq 0 ] || [ "$rc" -eq 1 ] || return "$rc"
}

echo "Backing up to $DEST"

echo "- PostgreSQL"
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' | gzip > "$DEST/postgres.sql.gz"

echo "- Documents (MinIO)"
archive minio /data minio.tar.gz

echo "- Vector index (Qdrant, paused for a few seconds)"
docker compose pause qdrant >/dev/null
trap 'docker compose unpause qdrant >/dev/null 2>&1 || true; cleanup_partial' EXIT
archive qdrant /qdrant/storage qdrant.tar.gz
docker compose unpause qdrant >/dev/null
trap cleanup_partial EXIT

echo "- Settings (.env)"
install -m 600 .env "$DEST/env.backup"

{
  echo "created=$(date -Iseconds)"
  echo "version=$(git describe --tags --always 2>/dev/null || echo unknown)"
  echo "host=$(hostname)"
} > "$DEST/manifest.txt"
(cd "$DEST" && sha256sum postgres.sql.gz minio.tar.gz qdrant.tar.gz env.backup > SHA256SUMS)

if [ -n "$GPG_RECIPIENT$PASSPHRASE_FILE" ]; then
  echo "- Encrypting"
  if [ -n "$GPG_RECIPIENT" ]; then
    gpg_args=(--encrypt --recipient "$GPG_RECIPIENT")
  else
    gpg_args=(--symmetric --cipher-algo AES256 --pinentry-mode loopback --passphrase-file "$PASSPHRASE_FILE")
  fi
  tar -C "$(dirname "$DEST")" -cf - "$(basename "$DEST")" | gpg --batch --yes "${gpg_args[@]}" -o "$DEST.tar.gpg"
  rm -rf "$DEST"
  DEST="$DEST.tar.gpg"
fi

complete=1
du -sh "$DEST" | awk '{print "Done: " $2 " (" $1 ")"}'

# Rotation of the default folder: complete backups only (a manifest, or an encrypted archive).
if [ "$DEFAULT_DEST" -eq 1 ] && [ "$KEEP" -gt 0 ] 2>/dev/null; then
  ls -1dt backups/mentis-* 2>/dev/null | while read -r b; do
    if [ -f "$b/manifest.txt" ] || [ "${b%.tar.gpg}" != "$b" ]; then echo "$b"; fi
  done | tail -n +"$((KEEP + 1))" | while read -r old; do
    echo "Removing old backup $old (keeping the newest $KEEP)"
    rm -rf "$old"
  done || true
fi
echo "Keep a copy off this server: backups on the same disk do not survive a disk failure."
