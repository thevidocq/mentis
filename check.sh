#!/usr/bin/env bash
# Post-install / post-upgrade check. Run from the repository root: ./check.sh
set -u

API_URL="${MENTIS_API_URL:-http://127.0.0.1:8000}"
fail=0

ok()   { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=1; }

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
body=$(curl -fsS --max-time 5 "$API_URL/api/health" 2>/dev/null) && ok "health: $body" || bad "health endpoint not reachable at $API_URL"
setup=$(curl -fsS --max-time 5 "$API_URL/api/setup/status" 2>/dev/null)
case "$setup" in
  *'"needs_setup":true'*)  echo "  INFO  first-run setup not done yet" ;;
  *'"needs_setup":false'*) ok "setup completed" ;;
  *) bad "setup status not readable" ;;
esac

echo
echo "Web:"
WEB_URL="${MENTIS_WEB_URL:-http://127.0.0.1:8080}"
curl -fsS --max-time 5 "$WEB_URL/" 2>/dev/null | grep -q '<div id="root">' && ok "frontend served at $WEB_URL" || bad "frontend not reachable at $WEB_URL"
curl -fsS --max-time 5 "$WEB_URL/api/health" >/dev/null 2>&1 && ok "API reachable through the web proxy" || bad "web proxy to API not working"

echo
if [ "$fail" -eq 0 ]; then echo "All checks passed."; else echo "Some checks failed. See: docker compose logs --tail=100"; fi
exit "$fail"
