# Beta 1 — estabilización Android 2.0

## Alcance y freeze

Beta 1 congela las capacidades de Alpha 2.0. No abre Alpha 2.1 ni añade dominios, métricas, IA, OCR, cloud, OAuth, telemetría, mapas, pagos o nuevas funciones BLE. La tanda se limita a defectos demostrados, regresiones, herramientas reproducibles, seguridad, rendimiento y documentación de QA.

- Rama exigida y observada: `beta/android-1.0-stabilization`.
- HEAD inicial: `28299103477b22eac6f569153236fa426d2a0619`.
- Versión Beta: code 21, `2.0.0-beta01`; debug resulta `2.0.0-beta01-debug`.
- Room permanece en 10 con schemas 1–10 y cadena explícita.
- Alembic permanece en `20260731_0036`, un solo head.
- `applicationId`, suffix debug, firma, SDKs y toolchain no cambian.

## Baseline reproducible

El árbol y staging comenzaron limpios. Los únicos avisos de Git fueron los directorios preexistentes e inaccesibles `qa-temp-alpha15*`, que no se leyeron, eliminaron ni modificaron. El inventario inicial encontró 166 JVM tests y 115 `androidTest`; la tanda añade seis JVM tests y ocho casos instrumentados de migración/reapertura.

El SDK observado dispone de platform-tools, emulator y build-tools 36, pero no de `avdmanager` en cmdline-tools. La única imagen instalada es API 37.1 `google_apis_playstore_ps16k/x86_64`; está prohibida por la política sin Play Store. El AVD preexistente `Pixel_7` no se arrancó ni modificó. Por ello ningún serial fue seleccionado y no se ejecutó un comando conectado.

Docker comenzó con dos contenedores diarios activos, dos volúmenes preexistentes y la red diaria. El baseline se obtuvo desde el daemon, sin ejecutar el Compose diario ni leer `.env`.

## Hallazgos y correcciones

| ID | Severidad | Módulo | Evidencia y causa | Corrección | Regresión | Riesgo residual |
| --- | --- | --- | --- | --- | --- | --- |
| B1-P1-001 | P1 | WorkManager/sync/Health Connect/engagement/portabilidad | `CancellationException` entraba en `catch Exception/Throwable` y podía convertirse en retry/failure o continuar otra operación tras logout/cambio de servidor. | Propagación común de cancelación estructurada en los cuatro workers, gateway/diagnóstico Health Connect, cola engagement, cola portable y borde Room. | `CancellationTest`; harness de cleanup/cancelación. | La carrera completa requiere AVD y permanece bloqueada. |
| B1-P1-002 | P1 | SAF/FileProvider/caché médica y actividades | IDs remotos se interpolaban en nombres de archivos. Un servidor incompatible podía introducir separadores y escapar del subdirectorio de caché privado. | Nombres opacos SHA-256 separados por propósito, validación de label/extensión y canonical-parent check; export fallido elimina su parcial. | `PrivateFileNamesTest`. | Compartir/visor externo real requiere QA físico. |
| B1-P2-001 | P2 | Mensaje de exportación | El mensaje de límite de exportación contenía mojibake visible. | Constante UTF-8 correcta. | `ActivityExportMessageTest`. | Ninguno conocido. |

No se encontró un P0 reproducible en los gates locales. No se cambió schema Room, contrato JSON ni persistencia backend.

## Matriz de integración revisada

Se revisaron login, refresh single-flight, sesión local, logout, cambio de servidor, bootstrap/pull/push, drafts, autosave, finalización offline, idempotencia, planificación, historial/progreso, salud, Health Connect, fuentes externas, BLE experimental, portabilidad, engagement, medical, activities, SAF/FileProvider, workers, receivers, notificaciones, migraciones, backup deshabilitado y seguridad de red. Los invariantes críticos son:

1. `accountScope` combina servidor normalizado y usuario; Room y archivos se filtran/particionan por scope.
2. El refresh cifrado está ligado al servidor y una respuesta vieja no reemplaza ni borra una sesión nueva.
3. Logout limpia el scope efectivo; cambio de servidor conserva filas aisladas pero invalida tokens/workers.
4. Toda mutación remota conserva UUID/idempotencia/revisión antes de la red.
5. SAF y FileProvider usan grants de lectura temporales, providers no exportados y rutas mínimas.
6. Notificaciones usan contenido privado, `publicVersion` genérica y `PendingIntent.FLAG_IMMUTABLE`.

## Gates automáticos

Resultados confirmados para el cierre:

- Backend: `compileall` correcto; pytest completo 716 passed, 9 skipped.
- Schemas: 77 schemas Draft 2020-12 válidos y todas las referencias locales presentes.
- Android final, en el orden prescrito: `lintDebug`; 172/172 JVM forzadas; `assembleDebug`; 123 tests `androidTest` compilados; segunda pasada 172/172 JVM forzadas.
- Harness PowerShell 5.1: 25 aserciones, sin Pester.
- MariaDB 11.4 efímera: 724 passed, 1 skipped; cero→0036, `db check` y dos ciclos 0036→0035→0036 aprobados.
- APK: package `io.healthtracker.companion.debug`, code 21, name `2.0.0-beta01-debug`, 18.213.405 bytes, firma v2 y cero hallazgos sensibles bloqueantes.
- Los detalles de gates y bloqueos se registran en [ANDROID_RELEASE_READINESS.md](ANDROID_RELEASE_READINESS.md).

Compilar `androidTest` no equivale a ejecutarlo. La ejecución conectada, Room físico 1→10, reapertura v10, `adb install -r`, modo avión, process death, reboot, notificaciones, SAF y WorkManager no se marcan aprobados mientras no exista una imagen instalada permitida.

## Room y actualización conservadora

`CompanionActivityMigrationTest` declara rutas independientes 1→10, 2→10, 3→10, 4→10, 5→10, 6→10, 7→10, 8→10, 9→10 y reapertura v10. Cada ruta 1–8 conserva una cuenta QA ficticia; 9→10 conserva la fixture previa. Las pruebas anteriores cubren preservación semántica de planificación, salud, Health Connect, fuentes, portabilidad, engagement y medical.

La ejecución física de estas rutas está bloqueada. Tampoco existe en el repositorio una APK Alpha anterior segura que pueda instalarse con la misma firma sin reconstruir un checkpoint; por ello `adb install -r` y preservación de DataStore/Keystore/drafts no se declaran aprobados. El procedimiento está en [BETA_1_PHYSICAL_QA_RUNBOOK.md](BETA_1_PHYSICAL_QA_RUNBOOK.md).

## Rendimiento y escala

La auditoría estática confirma índices compuestos de scope/servidor/fecha/estado para las tablas nuevas, límites de red/archivo, streaming de hashes y descargas, series/rutas fuera de Room y downsample acotado a 240 puntos. Se identifican como riesgos de medición pendiente las listas observables completas de actividades, estudios, objetivos y body stats. No se añadió un `LIMIT` sin medir porque alteraría comportamiento visible.

Los datasets de 1.000 sesiones, 5.000 body stats, 10.000 nutrition entries, 20.000 step records, 1.000 eventos, 500 estudios y 1.000 actividades no se ejecutaron: requieren Room en el AVD permitido. No se publican tiempos, memoria ni tamaño DB inventados.

## Seguridad y APK

El manifest mantiene backup deshabilitado, release sin cleartext, providers/receivers no exportados salvo las actividades requeridas por launcher/Health Connect, permisos BLE versionados, `POST_NOTIFICATIONS` y sin alarmas exactas. HTTP permanece solo en debug, explícito y limitado a hosts locales. No hay WebView, trust-all, hostname verifier custom, analytics ni body logging.

`scripts/beta/beta1_apk_audit.ps1` verificó package/version/SDK/debuggable, v2/v3, 19 permisos resultantes, 173 entradas y patrones sensibles sin imprimir coincidencias. El reporte externo registra SHA-256 `3758030fa28acbe579b90fc6ddcbfaa5a8b2d60d53cb6ba64592917ac4ebf5f9`, firma v2 presente, v3 ausente y cero hallazgos bloqueantes.

## Herramientas Beta

- `alpha20_beta1_common.ps1`: SDK/tools, imagen, selección segura, fingerprint, JSON y cleanup guard.
- `create_disposable_avd.ps1`: crea y arranca únicamente `health-tracker-beta1-qa-<id>` con imagen instalada sin Play.
- `run_beta1_instrumentation.ps1`: fija `ANDROID_SERIAL`, rechaza físicos/ambigüedad/package incorrecto y exporta resultados sanitizados.
- `delete_disposable_avd.ps1`: detiene y elimina únicamente el AVD ligado al session ID.
- `beta1_apk_audit.ps1`: auditoría reproducible del APK.
- `beta1_qa_report.ps1`: consolidación externa y gate de Git/staging.
- `run_beta1_mariadb.ps1`: migraciones y pytest contra red/contenedor exclusivos y MariaDB sobre tmpfs, con cleanup propio.
- `test_beta1_scripts.ps1`: 25 aserciones sin dispositivo ni Pester.

## Limitaciones y salida

Los gates locales, MariaDB efímera, APK y limpieza están verdes; Beta 1 queda técnicamente estabilizada para iniciar QA físico controlado. Continúan bloqueados o pendientes: AVD permitido, instrumentación ejecutada, upgrade real, modo avión/process death/reboot, rendimiento medido, layouts configurados, TalkBack manual, Health Connect real y restricciones OEM. No es una release final ni una aprobación física.
