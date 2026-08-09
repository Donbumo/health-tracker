#!/usr/bin/env sh
set -eu

usage() {
  cat <<'EOF'
Usage: alpha15_postdeploy_readonly.sh --env-file <path> --base-url <https-url> [--compose-file <path>] [--qa-token <token>]
Read-only postdeploy verification: services, readiness, Alembic current, public routes,
focused logs, and optional authenticated read-only smoke. It never restarts services or writes data.
EOF
}

ENV_FILE=""
COMPOSE_FILE="docker-compose.yml"
BASE_URL=""
QA_TOKEN=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --env-file) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; ENV_FILE=$2; shift 2 ;;
    --compose-file) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; COMPOSE_FILE=$2; shift 2 ;;
    --base-url) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; BASE_URL=$2; shift 2 ;;
    --qa-token) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; QA_TOKEN=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ] || { echo 'env file is required' >&2; exit 2; }
[ -f "$COMPOSE_FILE" ] || { echo 'compose file not found' >&2; exit 2; }
case "$BASE_URL" in https://*) ;; *) echo 'an explicit HTTPS base URL is required' >&2; exit 2 ;; esac

compose() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }
compose ps --status running
compose exec -T web flask db current
curl --fail --silent --show-error --max-time 10 "$BASE_URL/healthz" >/dev/null
curl --fail --silent --show-error --max-time 10 "$BASE_URL/api/v1/health" >/dev/null
compose logs --no-color --tail 80 web | grep -E 'ERROR|CRITICAL|Traceback|healthz|alembic' || true

if [ -n "$QA_TOKEN" ]; then
  SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
  ALPHA15_BASE_URL=$BASE_URL ALPHA15_BEARER_TOKEN=$QA_TOKEN \
    python3 "$SCRIPT_DIR/alpha15_smoke.py"
fi
echo 'POSTDEPLOY READ-ONLY PASS'
