#!/usr/bin/env bash
# Post-install / post-upgrade check. Run from the repository root: ./check.sh
set -u

cd "$(dirname "$0")" || exit 1
fail=0
# Web port from .env (MENTIS_WEB_PORT), default 8080.
# Quotes and Windows line endings are stripped (a .env edited on another system).
env_value() { [ -f .env ] && grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d "\"'\r" ; }
WEB_PORT="$(env_value MENTIS_WEB_PORT)"
# The address the port is bound to (MENTIS_WEB_BIND, 127.0.0.1 by default); 0.0.0.0 is reachable on 127.0.0.1.
WEB_HOST="$(env_value MENTIS_WEB_BIND)"
case "${WEB_HOST:-}" in ""|0.0.0.0) WEB_HOST=127.0.0.1 ;; *:*) WEB_HOST="[$WEB_HOST]" ;; esac
WEB_URL="${MENTIS_WEB_URL:-http://${WEB_HOST}:${WEB_PORT:-8080}}"
# Version of this checkout: after an upgrade the API must report it, or the new images are not running.
EXPECTED_VERSION="$(grep -E '^version = ' backend/pyproject.toml 2>/dev/null | head -1 | cut -d'"' -f2)"
# The API publishes no host port: ask it from inside its container.
api_get() {
  docker compose exec -T api python -c "import sys,urllib.request;sys.stdout.write(urllib.request.urlopen('http://127.0.0.1:8000$1',timeout=5).read().decode())" 2>/dev/null
}

ok()   { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=1; }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$1"; }

echo "Mentis check"
echo
echo "Containers:"
for svc in web api worker embeddings postgres qdrant minio redis; do
  ids=$(docker compose ps -q "$svc" 2>/dev/null)
  if [ -z "$ids" ]; then bad "$svc: not running"; continue; fi
  n=0
  for id in $ids; do
    n=$((n + 1))
    state=$(docker inspect -f '{{.State.Status}}' "$id")
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' "$id")
    label="$svc"; [ "$(echo "$ids" | wc -w)" -gt 1 ] && label="$svc #$n"
    if [ "$state" = "running" ] && { [ "$health" = "healthy" ] || [ "$health" = "n/a" ]; }; then
      ok "$label: $state ($health)"
    else
      bad "$label: $state ($health)"
    fi
  done
done

echo
echo "API:"
body=$(api_get /api/health) && [ -n "$body" ] && ok "health: $body" || bad "API health endpoint not answering"
if [ -n "$body" ] && [ -n "$EXPECTED_VERSION" ]; then
  case "$body" in
    *"\"version\":\"$EXPECTED_VERSION\""*) ok "version $EXPECTED_VERSION (matches this checkout)" ;;
    *) bad "API is not version $EXPECTED_VERSION of this checkout: rebuild with  docker compose up -d --build" ;;
  esac
fi
setup=$(api_get /api/setup/status)
case "$setup" in
  *'"needs_setup":true'*)  echo "  INFO  no super-admin yet: docker compose exec api python -m app.cli create-admin" ;;
  *'"needs_setup":false'*) ok "setup completed" ;;
  *) bad "setup status not readable" ;;
esac

echo
echo "Web:"
curl -fsS --max-time 5 "$WEB_URL/" 2>/dev/null | grep -q '<div id="root">' && ok "frontend served at $WEB_URL" || bad "frontend not reachable at $WEB_URL"
curl -fsS --max-time 5 "$WEB_URL/api/health" >/dev/null 2>&1 && ok "API reachable through the web proxy" || bad "web proxy to API not working"

echo
echo "Security:"
if [ -f .env ]; then
  mode=$(stat -c '%a' .env 2>/dev/null)
  case "$mode" in 600|400) ok ".env readable by its owner only ($mode)" ;; *) warn ".env permissions are $mode: run  chmod 600 .env" ;; esac
  grep -v '^[[:space:]]*#' .env | grep -q 'CHANGE_ME' && bad ".env still contains CHANGE_ME placeholders" || ok "no CHANGE_ME placeholders in .env"
fi
# Data services must stay on the internal network only (not on the web container's networks).
for svc in postgres qdrant minio redis embeddings; do
  id=$(docker compose ps -q "$svc" 2>/dev/null | head -1)
  [ -n "$id" ] || continue
  nets=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$id")
  extra=$(for n in $nets; do case "$n" in *_data|*_models) ;; *) printf '%s ' "$n" ;; esac; done)
  [ -z "$extra" ] && ok "$svc: isolated from the web and proxy networks" || bad "$svc: also on network(s) $extra"
  ports=$(docker inspect -f '{{range $p, $b := .NetworkSettings.Ports}}{{if $b}}{{$p}} {{end}}{{end}}' "$id")
  [ -z "$ports" ] || bad "$svc: publishes host port(s) $ports"
done

echo
echo "Storage:"
# Free space where Docker keeps volumes and images, and where backups are written.
root=$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)
for path in "$root" "$PWD"; do
  [ -d "$path" ] || continue
  read -r size used avail pct mount <<<"$(df -Ph "$path" | awk 'NR==2 {print $2, $3, $4, $5, $6}')"
  p=${pct%%%}
  if [ "${p:-0}" -ge 90 ]; then bad "disk $mount ($path) ${pct} full, $avail free of $size"
  elif [ "${p:-0}" -ge 80 ]; then warn "disk $mount ($path) ${pct} full, $avail free of $size"
  else ok "disk $mount ($path) ${pct} used, $avail free of $size"; fi
done
# Data volumes (documents, page images, index, database).
for vol in minio-data qdrant-data postgres-data embeddings-data; do
  name="$(basename "$PWD")_$vol"
  mp=$(docker volume inspect -f '{{.Mountpoint}}' "$name" 2>/dev/null) || continue
  sz=$(du -sh "$mp" 2>/dev/null | cut -f1)
  [ -n "$sz" ] && ok "volume $vol: $sz" || ok "volume $vol: size needs root (sudo ./check.sh)"
done
if [ -d backups ]; then
  n=$(ls -1d backups/mentis-* 2>/dev/null | wc -l)
  ok "backups/: $n backups, $(du -sh backups 2>/dev/null | cut -f1) (copy them off this server)"
fi
# Images and build cache left by upgrades.
df_out=$(docker system df --format '{{.Type}}={{.Reclaimable}}' 2>/dev/null)
img=$(printf '%s\n' "$df_out" | grep '^Images=' | cut -d= -f2)
cache=$(printf '%s\n' "$df_out" | grep '^Build Cache=' | cut -d= -f2)
[ -n "$img$cache" ] && ok "reclaimable: images ${img:-0B}, build cache ${cache:-0B} (free with: docker image prune -f && docker builder prune -f)"
logcfg=$(docker inspect -f '{{.HostConfig.LogConfig.Config}}' "$(docker compose ps -q api | head -1)" 2>/dev/null)
case "$logcfg" in *max-size*) ok "container logs rotated" ;; *) warn "container logs not rotated: docker compose up -d (v0.3.5+)" ;; esac

echo
if [ "$fail" -eq 0 ]; then echo "All checks passed."; else echo "Some checks failed. See: docker compose logs --tail=100"; fi
exit "$fail"
