# Handoff activo

## Alpha 1.7 en esta rama

- Rama: `feature/alpha-1.7-data-portability`; checkpoint inicial/HEAD: `8b2b7d86937ca33f118989cc6753b9fe8761bd75`, Alpha 1.6 completa.
- No se cambió de rama ni se usó staging, commit, push, merge o tag.
- Formato público `health-tracker-portable-v1` v1.0 (`.htpack`) con manifest, schemas embebidos, records JSON/JSONL, attachments opt-in y checksums SHA-256.
- Backend añade API Bearer owner-only de export/import, dry-run, conflictos, decisiones, remapeo, idempotencia, expiración y aplicación atómica.
- Alembic añade `20260730_0033`; modelos nuevos sólo para jobs, artefactos, decisiones y mappings portables.
- Android pasa a versionCode 17/versionName `1.7.0-alpha01`, Room 7 y `Ajustes → Datos y privacidad`; usa SAF, FileProvider, archivos privados por `accountScope` y WorkManager, incluida confirmación durable `pending_apply` al reconectar.
- Herramientas `scripts/portability/` inspeccionan, verifican, listan y crean una copia saneada sin mostrar records por defecto.
- Matriz de dominio, formato y privacidad: `ALPHA_1_7_DATA_PORTABILITY.md`, `PORTABLE_PACKAGE_FORMAT_V1.md` y `DATA_EXPORT_PRIVACY.md`.
- El mapa canónico de contexto permanece en `DOCUMENTATION_INDEX.md`.

## Estado actual

- La implementación solicitada está completa y permanece sin staging.
- No se ejecutarán instrumentadas conectadas, instalación APK, NAS ni Compose diario.

## Pruebas relevantes

- Backend local final: 643 correctas, 4 omitidas (carreras sólo Docker), un warning intencional de ZIP duplicado del backup histórico.
- Docker/MariaDB: suite completa 645 correctas/1 omitida y carrera focal portable 1/1; cero→0033, check, downgrade a 0032 y re-upgrade correctos.
- Android: `lintDebug`, dos JVM forzadas 149/149, `assembleDebug` y `compileDebugAndroidTestKotlin` correctos.
- Los tests cubren round-trip, repetición sin duplicados, foreign collision, conflicto conservador, rollback, attachments, expiración, ZIP safety, schemas, CLI y migraciones Room 1/2/3/4/5/6→7.
- APK debug: 18.930.583 bytes, SHA-256 `3080e9e04c309cdd22629827b53c6c8781c880250dc2a0bf848b712d59fbf527`, firma v2 válida, code 17/name `1.7.0-alpha01-debug`; escaneo sensible limpio.

## Trabajo en curso

- Sólo quedan revisión humana del diff y QA manual/físico posterior; los gates automáticos Alpha 1.7 están completos.

## Bloqueadores y riesgos

- SHA-256 no prueba autenticidad y Alpha 1.7 no cifra/firma paquetes.
- La generación backend es síncrona y acotada.
- La inspección Android es una barrera temprana; el servidor repite la validación autoritativa completa.
- QA físico, ejecución instrumentada en entorno aislado y revisión humana siguen pendientes.
- Los directorios inaccesibles `qa-temp-alpha15*` son preexistentes y deben permanecer intactos.

## Siguiente paso

Revisar el diff sin añadirlo al staging y programar QA manual en un AVD/dispositivo aislado. No declarar autenticidad criptográfica ni QA físico no realizado.
