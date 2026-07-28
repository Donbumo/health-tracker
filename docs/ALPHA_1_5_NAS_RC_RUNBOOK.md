# Alpha 1.5 RC1 en NAS y teléfono Android

Este runbook prepara una prueba privada de `feature/alpha-1.5-health-connect`. No sustituye una ventana de mantenimiento, una copia verificada ni la aprobación humana. Los servicios reales de Compose son `web` y `db`; los dumps, metadatos y APK deben guardarse fuera del repositorio.

## Antes de tocar el NAS

1. Acordar una ventana y detener nuevas escrituras desde web y Android.
2. Confirmar rama/revisión y guardar la revisión anterior fuera del repo:

   ```sh
   git branch --show-current
   git rev-parse HEAD
   git status --short --branch
   git rev-parse HEAD > "$BACKUP_DIR/app-revision-before.txt"
   docker compose exec -T web flask db current | tee "$BACKUP_DIR/alembic-before.txt"
   ```

3. Ejecutar el preflight sin iniciar, reiniciar ni migrar servicios:

   ```sh
   HT_ENV_FILE=.env sh scripts/release/alpha15_nas_preflight.sh
   ```

   El archivo indicado debe ser la configuración privada real; `.env.example` se rechaza. El script solo informa nombres/estados y nunca valores.

## Respaldo lógico

Define `BACKUP_DIR` como un directorio protegido fuera del checkout. No copies secretos, dumps ni metadatos operativos al repositorio.

```sh
BACKUP_FILE="$BACKUP_DIR/health-tracker-before-alpha15.sql"
docker compose exec -T db sh -c 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb-dump --user=root --single-transaction --routines --triggers "$MARIADB_DATABASE"' > "$BACKUP_FILE"
test -s "$BACKUP_FILE"
sha256sum "$BACKUP_FILE" > "$BACKUP_FILE.sha256"
docker compose config --images > "$BACKUP_DIR/compose-images-before.txt"
```

Protege el directorio y comprueba que el dump no está vacío. Ensaya la restauración en MariaDB aislada antes de depender del archivo. Registrar revisión Git, revisión Alembic, fecha, operador y hashes es suficiente; no copies `.env`, claves ni certificados.

## Actualización y migración

Tras subir la rama por el flujo humano aprobado, en el NAS:

```sh
git fetch origin
git switch feature/alpha-1.5-health-connect
git pull --ff-only origin feature/alpha-1.5-health-connect
docker compose build web
docker compose run --rm --no-deps --entrypoint flask web db upgrade
docker compose run --rm --no-deps --entrypoint flask web db check
docker compose up -d --no-deps web
docker compose ps
docker compose exec -T web flask db current
```

El comando previo y posterior de revisión es `docker compose exec -T web flask db current`; el head esperado es `20260726_0032`. La entrada normal de `web` vuelve a ejecutar `flask db upgrade` de forma idempotente antes de Gunicorn.

Para un reverse proxy de un salto, expón `web` solo al proxy, termina TLS allí, usa un certificado válido y configura `PROXY_FIX_X_PROTO=1`; deja `PROXY_FIX_X_FOR=0` salvo que realmente necesites la IP original. Los valores 0 son el default local y no se confía en headers reenviados. Nunca publiques el puerto de backend directamente mientras ProxyFix esté habilitado. `SESSION_COOKIE_SECURE=true` corresponde a acceso web exclusivamente HTTPS.

## Smoke contra el NAS

Usa una cuenta QA y entrega el token solo por variable de entorno o argumento local; la herramienta no lo imprime ni lo guarda. Read-only es el default y valida TLS:

```sh
ALPHA15_BASE_URL=https://tracker.example.test ALPHA15_BEARER_TOKEN='token-efimero-qa' \
  python scripts/release/alpha15_smoke.py
```

HTTP requiere `--allow-http` y solo se admite para una LAN QA explícita. El modo write exige dos opciones deliberadas, usa recursos ficticios futuros y confirma su limpieza:

```sh
python scripts/release/alpha15_smoke.py --base-url https://tracker.example.test \
  --token 'token-efimero-qa' --write --confirm-write QA-ALPHA15-WRITE
```

Read-only cubre readiness, API health, perfil, negociación existente, sync, historial, progreso, salud y catálogos. Health Connect settings es local al APK y se reporta como `SKIP`. Write crea/repite/actualiza/consulta/elimina una medición QA, crea/repite pasos QA y verifica que ambos desaparecieron.

## Rollback

Elige el nivel mínimo necesario:

1. **Aplicación sin downgrade de DB.** Detén escrituras, registra el fallo, vuelve al commit anterior aprobado, reconstruye `web` y levántalo conservando 0032. Es la primera opción si la versión anterior tolera las columnas aditivas.
2. **Downgrade 0032→0031.** Solo con backup verificado y tras comprobar que no hay pesos manuales y Health Connect coexistiendo en el mismo instante. Ejecuta en ventana cerrada:

   ```sh
   docker compose stop web
   docker compose run --rm --no-deps --entrypoint flask web db downgrade 20260726_0031
   docker compose run --rm --no-deps --entrypoint flask web db current
   ```

   El downgrade elimina `client_event_id` y procedencia añadida en 0032; puede ser destructivo y la propia migración se niega ante duplicados incompatibles. No lo uses como reacción automática.
3. **Restauración completa.** Solo si aplicación y migración dejaron la base inutilizable. Mantén `web` detenido, recrea una base vacía por el procedimiento del operador, restaura el dump con MariaDB, verifica su hash/revisión y levanta la versión anterior. Esto reemplaza estado posterior al backup y exige aprobación explícita.

Nunca uses `docker compose down -v` como rollback.

## APK y actualización conservadora

Usa el APK debug producido por el gate y no desinstales ni limpies la app:

```text
adb devices -l
adb install -r <apk>
adb shell monkey -p io.healthtracker.companion.debug -c android.intent.category.LAUNCHER 1
```

`adb install -r` conserva Room, DataStore, SharedPreferences cifradas y Keystore cuando applicationId y firma coinciden. Si Android rechaza la actualización, detente: no uses `adb uninstall` ni `pm clear`; compara applicationId, firma y versionCode.

## Recorrido real de teléfono

Este recorrido sigue pendiente hasta ejecutarse en un teléfono de QA con datos ficticios:

1. Abrir la aplicación.
2. Configurar URL del NAS.
3. Iniciar sesión.
4. Cerrar proceso y abrir.
5. Ver Hoy.
6. Descargar entrenamiento.
7. Iniciar offline.
8. Registrar una serie.
9. Cerrar proceso.
10. Recuperar draft.
11. Completar.
12. Recuperar conexión.
13. Confirmar autosync.
14. Crear plan.
15. Programar entrenamiento.
16. Confirmarlo en Hoy.
17. Registrar peso.
18. Registrar comida.
19. Registrar pasos.
20. Confirmar datos en web.
21. Conectar Health Connect.
22. Conceder solo peso y pasos.
23. Importar.
24. Confirmar procedencia.
25. Revocar pasos.
26. Confirmar que peso continúa funcionando.
27. Desconectar el servidor poniendo el teléfono offline, sin cambiar la URL ni borrar la sesión.
28. Registrar un dato local.
29. Reconectar.
30. Confirmar una sola copia en web.

Resultado: pendientes 0, conflictos 0, una sesión, una programación, salud sin duplicados, sin logout inesperado, crash ni secretos en logcat.

## Logs focalizados

Android, sin volcar el log completo ni headers:

```text
adb logcat -d -t 300 AndroidRuntime:E ActivityManager:E '*:S'
adb logcat -d -t 500 | grep -Ei 'ANR|Room|draft_|HealthConnect|network_|contract_decode_failed'
adb logcat -d -t 500 | grep -Ei 'Authorization|Bearer |access_token|refresh_token|password'
```

Docker, siempre acotado:

```sh
docker compose logs web --since 15m --tail 300 | grep -Ei '/api/v1| 4[0-9][0-9] | 5[0-9][0-9] |migration|traceback|worker timeout'
docker compose logs db --since 15m --tail 200 | grep -Ei 'error|warning|crash|ready'
```

No compartas líneas que contengan datos de salud, identificadores completos o secretos; redacta antes de adjuntar.
