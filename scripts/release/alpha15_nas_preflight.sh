#!/bin/sh
set -eu

EXPECTED_HEAD="20260726_0032"
MIN_FREE_KB="${ALPHA15_MIN_FREE_KB:-2097152}"
ENV_FILE="${HT_ENV_FILE:-.env}"

fail() {
    printf 'PRECHECK FAIL: %s\n' "$1" >&2
    exit 1
}

ok() {
    printf 'PRECHECK OK: %s\n' "$1"
}

[ -f "docker-compose.yml" ] && [ -d "backend/migrations/versions" ] \
    || fail "ejecuta el script desde la raíz del repositorio"
command -v docker >/dev/null 2>&1 || fail "Docker no está disponible"
docker info >/dev/null 2>&1 || fail "el daemon de Docker no responde"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 no está disponible"
ok "Docker y Compose disponibles"

case "$ENV_FILE" in
    *.env.example|*.example) fail "no uses .env.example como configuración real" ;;
esac
[ -f "$ENV_FILE" ] || fail "falta el archivo de entorno indicado por HT_ENV_FILE"

for name in MARIADB_DATABASE MARIADB_USER MARIADB_PASSWORD MARIADB_ROOT_PASSWORD SECRET_KEY ADMIN_USERNAME ADMIN_PASSWORD; do
    awk -F= -v key="$name" '
        $0 !~ /^[[:space:]]*#/ && $1 ~ "^[[:space:]]*" key "[[:space:]]*$" {
            value=substr($0, index($0, "=")+1)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            empty_single=sprintf("%c%c", 39, 39)
            if (length(value) > 0 && value !~ /^#/ && value != "\"\"" && value != empty_single) found=1
        }
        END { exit(found ? 0 : 1) }
    ' "$ENV_FILE" || fail "falta una variable requerida o está vacía: $name"
done
ok "variables requeridas presentes (valores no mostrados)"

if ! docker compose --env-file "$ENV_FILE" config --quiet >/dev/null 2>&1; then
    fail "docker compose config no es válido"
fi
services="$(docker compose --env-file "$ENV_FILE" config --services 2>/dev/null)"
printf '%s\n' "$services" | grep -qx 'db' || fail "el servicio db no está definido"
printf '%s\n' "$services" | grep -qx 'web' || fail "el servicio web no está definido"
ok "servicios esperados db y web definidos"

free_kb="$(df -Pk . | awk 'NR==2 {print $4}')"
case "$free_kb" in ''|*[!0-9]*) fail "no fue posible determinar el espacio libre" ;; esac
[ "$free_kb" -ge "$MIN_FREE_KB" ] || fail "espacio libre insuficiente para el umbral configurado"
ok "espacio libre suficiente"

revision="$(git rev-parse --verify HEAD 2>/dev/null)" || fail "no fue posible identificar la revisión Git"
printf 'Git revision: %.12s\n' "$revision"
[ -f "backend/migrations/versions/20260726_0032_health_connect_read_import.py" ] \
    || fail "no existe la migración esperada 0032"
printf 'Alembic expected head: %s\n' "$EXPECTED_HEAD"

running="$(docker compose --env-file "$ENV_FILE" ps --status running --services 2>/dev/null)"
printf '%s\n' "$running" | grep -qx 'db' || fail "db no está ejecutándose; el preflight no inicia servicios"
printf '%s\n' "$running" | grep -qx 'web' || fail "web no está ejecutándose; el preflight no inicia servicios"

docker compose --env-file "$ENV_FILE" exec -T db healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1 \
    || fail "MariaDB no acepta conexiones desde su contenedor"
ok "conectividad MariaDB"

current="$(docker compose --env-file "$ENV_FILE" exec -T web flask db current 2>/dev/null)" \
    || fail "no fue posible consultar la revisión Alembic actual"
case "$current" in
    *20260726_0032*) ok "base ya está en 0032" ;;
    *20260726_0031*) printf 'PRECHECK INFO: migración 0031 -> 0032 pendiente\n' ;;
    *) fail "la revisión Alembic actual no es 0031 ni 0032" ;;
esac

printf 'PRECHECK READY: no se aplicaron migraciones, no se reiniciaron servicios y no se modificó almacenamiento.\n'
