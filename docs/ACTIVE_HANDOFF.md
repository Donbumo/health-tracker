# Handoff activo

## Alpha 2.0 en esta rama

- Rama `feature/alpha-2.0-activity-interchange`; checkpoint inicial/HEAD sin modificar `350cf2` (Alpha 1.9 completa). No se cambió de rama ni se usó staging.
- Backend normaliza FIT/GPX/TCX a `health-tracker-activity-v1`, separa inspección de confirmación, conserva archivos originales privados y guarda series/rutas comprimidas fuera de MariaDB. Alembic `20260731_0036` es aditiva y reversible.
- API Bearer owner-only ofrece imports, actividades, laps, series paginadas, ruta, exports y vínculo/comparación con planes. Solo duplicados exactos se resuelven automáticamente.
- Android pasa a code 20/name `2.0.0-alpha01`, Room 10 y nueve tablas cuenta+servidor. Historial abre Actividades; SAF y WorkManager permiten selección/hash/cola offline, y la UI dibuja series y ruta localmente.
- Portable v1 añade actividades, laps, links, comparaciones y series. Coordenadas y series densas requieren opt-ins separados; los archivos originales nunca viajan.
- Documentación canónica: `ALPHA_2_0_ACTIVITY_INTERCHANGE.md`, `ACTIVITY_STANDARD_V1.md`, `ACTIVITY_LOCATION_PRIVACY.md` y `PLAN_VS_ACTUAL.md`.
- Gate final: backend local 716/9; matriz Docker/MariaDB 92/92 con concurrencia y E2E FIT/GPX/plan/portabilidad. Alembic pasó cero→0036, 0035→0036, check y dos ciclos downgrade/re-upgrade.
- Android pasó en orden `lintDebug`, 166/166 JVM forzadas, `assembleDebug`, `compileDebugAndroidTestKotlin` y segunda JVM forzada 166/166. El APK debug mide 18.197.013 bytes, SHA-256 `C32AC0352FDE62EC9144BABEB4A38667E0C9E2E818289E451CC2839AADED21D7`, firma v2 y code 20/name `2.0.0-alpha01-debug`; el escaneo sensible quedó limpio.
- MariaDB usó contenedores/red exclusivos, tmpfs y storage temporal externo; todos se eliminaron. Volúmenes antes/después: los mismos dos preexistentes. Compose diario, `.env`, `/data`, NAS y `qa-temp-alpha15*` no se tocaron.
- QA físico, instrumentación conectada y archivos reales permanecen fuera de alcance.

## Alpha 1.9 en esta rama

- Rama `feature/alpha-1.9-medical-records`; checkpoint inicial/HEAD sin modificar `2644b58a8cd41c0e516773980697f353102a76db` (Alpha 1.8 completa).
- Backend añade estudios, fuentes, paneles, resultados/revisiones, documentos, duplicados y auditoría sanitizada mediante Alembic `20260731_0035`, endpoints Bearer owner-only e import `health-tracker-medical-lab-v1` JSON/CSV con preview.
- Storage reutiliza `UploadedFile`; PDF/JPEG/PNG/JSON interno/CSV controlado usan detección real, SHA-256, nombres aleatorios y límites. No hay OCR, IA, diagnóstico, antivirus simulado ni rangos universales.
- Android pasa a code 19/name `1.9.0-alpha01`, Room 9 y nueve tablas aisladas por cuenta+servidor; Salud contiene estudios/laboratorio, SAF, FileProvider privado y cola offline durable.
- Portable v1 añade cuatro secciones estructuradas. Los documentos originales permanecen desactivados por defecto y requieren `include_medical_attachments=true`.
- Documentación canónica de la entrega: `ALPHA_1_9_MEDICAL_RECORDS.md`, `MEDICAL_DATA_PRIVACY.md` y `MEDICAL_LAB_FORMAT_V1.md`.
- Gates finales: backend local 687/7 y Docker/MariaDB 693/1; el único omitido en Docker es el test documental que no se copia a la imagen. Alembic pasó cero→0035, 0034→0035, check, downgrade y re-upgrade; concurrencia médica y E2E completo pasaron sobre storage efímero.
- Android pasó en orden `lintDebug`, 157/157 JVM forzadas, `assembleDebug`, `compileDebugAndroidTestKotlin` y segunda JVM forzada 157/157. El APK debug mide 20.513.670 bytes, SHA-256 `05E624AAE2137F063BD4B3866665DB03FF36DA6FFB109C54AF865F63F770E6F7`, firma v2, code 19/name `1.9.0-alpha01-debug` y escaneo sensible limpio.
- MariaDB usó un contenedor/red exclusivos, `/var/lib/mysql` en tmpfs y storage de aplicación bajo temporal externo; los recursos e imágenes QA se eliminaron. Volúmenes antes/después: los mismos dos preexistentes. Compose diario, `.env`, `/data`, NAS y `qa-temp-alpha15*` no se tocaron.
- QA físico, instrumentación conectada, OCR/IA/FHIR e interpretación clínica permanecen fuera de alcance.

## Alpha 1.8 en esta rama

- Rama `feature/alpha-1.8-goals-reminders-adherence`; checkpoint inicial/HEAD sin modificar `a5cee0add8448516428f3044c70a3a03058139ac`.
- Objetivos y reglas owner-only con API Bearer, idempotencia, revisión optimista, adherencia 7/30/90 y Alembic `20260731_0034` aditiva/reversible.
- Android versionCode 18/versionName `1.8.0-alpha01`, Room 8, cola offline con coalescing y aislamiento por `accountScope` e identidad hash del servidor.
- WorkManager agenda avisos locales sin alarmas exactas; canales separados, permiso contextual, lockscreen privado, quiet hours, snooze hijo, dedupe y antispam.
- Se conservan cinco pestañas: Ajustes abre configuración/centro interno, Hoy limita objetivos a tres y Progreso muestra caché descriptiva.
- Portable v1 añade opcionalmente `goals` y `reminder_rules`; nunca transporta eventos, permisos, schedules, channels o ledger.
- Arquitectura y QA pendiente: `ALPHA_1_8_GOALS_REMINDERS.md`, `NOTIFICATION_PRIVACY.md` y `ADHERENCE_METRICS.md`.
- Gates: backend local 657/5 y MariaDB 661/1; Android lint, 154/154 JVM dos veces, APK y compilación androidTest correctos. APK debug 17.835.620 bytes, SHA-256 `4511c25e69e2f3476a229a5ea2b97e573854ead9848136affa86206ae8cbcd8c`, firma v2, code 18/name `1.8.0-alpha01-debug`.
- MariaDB usó un contenedor/red exclusivos y tmpfs; contenedor, red e imagen QA se eliminaron. Volúmenes antes/después: los mismos dos preexistentes. Compose diario, `.env`, `/data`, NAS y `qa-temp-alpha15*` no se tocaron.

## Checkpoint Alpha 1.7 de partida

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
