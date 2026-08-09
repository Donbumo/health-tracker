# Alpha 1.5 RC1 en NAS y teléfono Android

Runbook para una prueba privada de `feature/alpha-1.5-health-connect`. Requiere ventana humana, cuenta QA ficticia, backup externo verificado y TLS válido. No copies `.env`, tokens, dumps, APK, certificados ni datos personales al repositorio. Sustituye únicamente los placeholders en mayúsculas.

## A. Windows: revisión, commit y artefacto

```powershell
git branch --show-current
git status --short --branch
git diff --check
git diff --stat
git diff --name-status
git diff --cached --name-only
git add -u
git add -- backend/tests/test_alpha15_real_journey.py scripts/release/alpha15_apk_manifest.ps1 scripts/release/alpha15_phone_preflight.ps1 scripts/release/alpha15_postdeploy_readonly.sh
git diff --cached --check
git commit -m "chore(release): harden alpha 1.5 RC1 operations"
git push origin feature/alpha-1.5-health-connect
git rev-parse HEAD
powershell -ExecutionPolicy Bypass -File scripts/release/alpha15_apk_manifest.ps1 -ApkPath '<APK_PATH>'
Get-FileHash -Algorithm SHA256 -LiteralPath '<APK_PATH>'
```

Antes de `git add`, confirma que no aparece `.env`, `data/`, `local.properties`, `build/`, APK, keystore, dump, backup, base o captura. El manifiesto JSON generado junto al APK es local e ignorado; no lo versiones.

## B. NAS antes del despliegue

Acordar la ventana y detener nuevas escrituras desde web y Android antes del backup.

```sh
cd <CHECKOUT_PATH>
git status --short --branch
git fetch origin feature/alpha-1.5-health-connect
export BACKUP_DIR=<PROTECTED_BACKUP_DIR>
mkdir -p "$BACKUP_DIR"
git rev-parse HEAD > "$BACKUP_DIR/app-revision-before.txt"
docker compose --env-file <ENV_FILE> ps
docker compose --env-file <ENV_FILE> exec -T web flask db current | tee "$BACKUP_DIR/alembic-before.txt"
docker compose --env-file <ENV_FILE> exec -T db sh -c 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb-dump --user=root --single-transaction --routines --triggers "$MARIADB_DATABASE"' > "$BACKUP_DIR/health-tracker-before-alpha15.sql"
test -s "$BACKUP_DIR/health-tracker-before-alpha15.sql"
sha256sum "$BACKUP_DIR/health-tracker-before-alpha15.sql" > "$BACKUP_DIR/health-tracker-before-alpha15.sql.sha256"
docker compose --env-file <ENV_FILE> config --images > "$BACKUP_DIR/compose-images-before.txt"
HT_ENV_FILE=<ENV_FILE> sh scripts/release/alpha15_nas_preflight.sh
git switch feature/alpha-1.5-health-connect
git merge --ff-only origin/feature/alpha-1.5-health-connect
test "$(git rev-parse HEAD)" = "<APPROVED_RC_SHA>"
```

Ensaya la restauración del dump en una MariaDB aislada. El preflight solo informa nombres y estados; nunca valores. El head esperado tras el despliegue es `20260726_0032`.

## C. NAS: despliegue y verificación

```sh
docker compose --env-file <ENV_FILE> build web
docker compose --env-file <ENV_FILE> run --rm --no-deps --entrypoint flask web db upgrade
docker compose --env-file <ENV_FILE> run --rm --no-deps --entrypoint flask web db check
docker compose --env-file <ENV_FILE> up -d --no-deps web
docker compose --env-file <ENV_FILE> ps
docker compose --env-file <ENV_FILE> exec -T web flask db current
sh scripts/release/alpha15_postdeploy_readonly.sh --env-file <ENV_FILE> --base-url https://<PUBLIC_HOST>
ALPHA15_BASE_URL=https://<PUBLIC_HOST> ALPHA15_BEARER_TOKEN=<EPHEMERAL_QA_TOKEN> python3 scripts/release/alpha15_smoke.py
ALPHA15_BASE_URL=https://<PUBLIC_HOST> ALPHA15_BEARER_TOKEN=<EPHEMERAL_QA_TOKEN> python3 scripts/release/alpha15_smoke.py --write --confirm-write QA-ALPHA15-WRITE
docker compose --env-file <ENV_FILE> logs --no-color --since 15m --tail 300 web | grep -Ei ' 4[0-9][0-9] | 5[0-9][0-9] |migration|traceback|worker timeout'
docker compose --env-file <ENV_FILE> logs --no-color --since 15m --tail 200 db | grep -Ei 'error|warning|crash|ready'
```

Read-only cubre readiness, salud API, perfil, negociación, sync, historial, progreso, salud y catálogos. El modo write usa recursos ficticios futuros, prueba idempotencia y confirma su eliminación. Health Connect settings es local al APK y aparece como `SKIP`.

Para un reverse proxy de un salto, expón `web` solo al proxy, termina TLS allí, usa certificado válido y configura `PROXY_FIX_X_PROTO=1`. Mantén `PROXY_FIX_X_FOR=0` salvo necesidad verificada y `SESSION_COOKIE_SECURE=true` con acceso exclusivamente HTTPS. Nunca publiques el backend directo mientras ProxyFix esté activo.

## D. Teléfono: preflight, actualización y recorrido

```powershell
powershell -ExecutionPolicy Bypass -File scripts/release/alpha15_phone_preflight.ps1 -ApkPath '<APK_PATH>' -Serial '<DEVICE_SERIAL>'
adb -s '<DEVICE_SERIAL>' install -r '<APK_PATH>'
adb -s <DEVICE_SERIAL> shell monkey -p io.healthtracker.companion.debug -c android.intent.category.LAUNCHER 1
adb -s <DEVICE_SERIAL> logcat -c
# Ejecutar el recorrido manual siguiente.
adb -s <DEVICE_SERIAL> logcat -d -t 500 AndroidRuntime:E ActivityManager:E '*:S'
```

`adb install -r` conserva Room, DataStore, SharedPreferences cifradas y Keystore cuando applicationId y firma coinciden. Si el preflight o Android rechazan firma, package o versionCode, detente: no desinstales ni uses `pm clear`.

Recorrido manual pendiente:

1. Configurar URL HTTPS del NAS e iniciar sesión.
2. Cerrar proceso, abrir, verificar Hoy y descargar un entrenamiento.
3. Pasar offline, iniciar, registrar serie, cerrar proceso y recuperar draft.
4. Completar offline, reconectar y confirmar autosync sin duplicados.
5. Crear plan, programar entrenamiento y confirmarlo en Hoy.
6. Registrar peso, comida y pasos; confirmar una sola copia en web.
7. Conectar Health Connect y conceder solo peso y pasos.
8. Importar, confirmar procedencia, revocar pasos y comprobar que peso continúa.
9. Poner el servidor offline sin cambiar URL ni borrar sesión, registrar un dato local, reconectar y comprobar una sola copia.
10. Terminar con pendientes 0, conflictos 0, una sesión, una programación, sin logout, crash ni secretos en logcat.

No compartas logs con datos de salud, IDs completos o secretos. Para una revisión focal adicional:

```text
adb -s <DEVICE_SERIAL> logcat -d -t 500 | grep -Ei 'ANR|Room|draft_|HealthConnect|network_|contract_decode_failed'
adb -s <DEVICE_SERIAL> logcat -d -t 500 | grep -Ei 'Authorization|Bearer |access_token|refresh_token|password'
```

## E. Rollback

Primera opción: volver a la aplicación anterior y conservar 0032 si tolera columnas aditivas.

```sh
cd <CHECKOUT_PATH>
docker compose --env-file <ENV_FILE> stop web
git switch --detach <PREVIOUS_APPROVED_SHA>
docker compose --env-file <ENV_FILE> build web
docker compose --env-file <ENV_FILE> up -d --no-deps web
docker compose --env-file <ENV_FILE> exec -T web flask db current
```

Solo si existe backup válido y el guard confirma que no se perderá información Alpha 1.5:

```sh
docker compose --env-file <ENV_FILE> stop web
docker compose --env-file <ENV_FILE> run --rm --no-deps --entrypoint flask web db downgrade 20260726_0031
docker compose --env-file <ENV_FILE> run --rm --no-deps --entrypoint flask web db current
```

El downgrade se niega **antes de cualquier DDL** si encuentra `client_event_id`, nutrición no manual o pesos coexistentes que perderían procedencia. La restauración del dump es el último recurso, requiere aprobación y reemplaza todas las escrituras posteriores al backup. Nunca uses `docker compose down -v` como rollback.
