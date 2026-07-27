# Handoff activo

## Alpha 1.4 — registro diario de salud Android (26 de julio de 2026)

- Rama obligatoria: `feature/alpha-1.4-mobile-health-logging`; no realizar commit/push/merge/tag desde este handoff.
- Backend: endpoints Bearer owner-only para resumen/progreso, cuerpo, nutrición, catálogo privado y pasos; UUID/revisiones añadidos a los modelos existentes mediante migración `20260726_0031`. `daily_energy` permite coexistencia por fecha/fuente y la lectura efectiva prioriza `manual` sin sumar fuentes.
- Android: `1.4.0-alpha01`, Room 4 preservador, tarjetas de salud en Hoy, pantallas anidadas, registro offline, UUID/idempotencia, coalescing, autosync, conflictos visibles/resolubles y Progreso Salud con alternativa textual.
- Validación: backend `612 passed, 1 skipped` en Python 3.13 + MariaDB 11.4 efímera; schema JSON, compileall, Compose config, single head `0031`, `db check` y ciclo upgrade/downgrade/upgrade verdes. Android lint, dos pasadas JVM (53/53), APK y compilación androidTest verdes.
- No se ejecutó `connectedDebugAndroidTest`; continúan pendientes QA manual visual/accesible, modo avión→process death→reconexión y verificación web↔Android en AVD/dispositivo separado.

## Base preservada de Alpha 1.3

### Alpha 1.3 — planificación Android (25 de julio de 2026)

- Rama obligatoria: `feature/alpha-1.3-mobile-planning`; no realizar commit/push/merge/tag desde este handoff.
- Backend: catálogo paginado por nombre/alias, agregado mutable `TrainingPlanWorkout`, versiones inmutables, CRUD/duplicación/archivo/orden, agenda acotada y schedule/move/cancel owner-only e idempotente, bloqueo seguro de archivo con programaciones activas, `training_plan` en el cursor compartido y package determinista por revisión.
- Android: `1.3.0-alpha01`, Room 3 preservador, agenda semana/mes y Today desde la fuente local, UUID de programación estable, coalescing/FIFO, autosave/autosync, conflictos resolubles, packages protegidos ante drafts activos y completion local inmediato en Historial/Progreso.
- Contratos: `training_plan.schema.json` ampliado de forma aditiva y nuevo read model `mobile_planning.schema.json`; no hay segundo cursor ni nuevo motor de sesiones.
- Validación final: Android lint/49 JVM/APK/androidTest compile/49 JVM verdes; backend local `600 passed, 3 skipped` y Docker/MariaDB efímero `602 passed, 1 skipped`; compileall, 30 schemas, single head, `db check`, ciclo upgrade/downgrade/upgrade de 0030 y Compose config verdes.
- Pendiente fuera de esta implementación: instrumentación en AVD separado y QA manual visual/offline/process death/package revision/accesible. No usar ni limpiar el AVD reservado.

Actualizado: 2026-07-25.

## Base preservada de Alpha 1.2

- La rama `feature/alpha-1.3-mobile-planning` conserva íntegramente el cierre de Alpha 1.2 descrito a continuación.
- Checkpoint comprobado al iniciar: `86b5f9f00104bfad5a9df655726743b0be8a93b0`, con Alpha 1.1 completo.
- Alpha 1.2 añade API Bearer owner-only para historial paginado/detalle y progreso por periodo/ejercicio, con contratos JSON públicos y UUID persistente de `Exercise` y de cada ocurrencia histórica.
- Android Room 2 conserva Alpha 1.1 y añade cache estructurada de páginas, detalle, resúmenes, puntos y marcas por `accountScope`; completion offline aparece pendiente y se reconcilia por `client_event_id`.
- La navegación principal es Hoy, Historial, Progreso y Ajustes. Las gráficas Canvas de carga/volumen incluyen resumen textual y manejan cero, uno o valores iguales.
- El código fuente de Android Companion Alpha 1.2 está implementado en `../android/`: conserva login, configuración segura de servidor, negociación, ejecución y cola offline, y suma historial/progreso local-first en Room.
- La migración backend `20260724_0029` añade y rellena los UUID públicos sin perder registros; la migración Room 1→2 conserva las sesiones recientes y crea el cache estructurado nuevo.
- La persistencia de start/draft/set usa `Upsert` y transacciones; el caso QA `test1` fue recuperado como activo con pendientes/conflictos en cero sin borrar datos.
- Hoy, Historial, Progreso y Ajustes representan estados humanos de conexión/sync/cola; la ejecución conserva su ruta propia y las acciones quedan protegidas hasta que complete/abort son durables.
- Process death sin red permite reanudar cache autorizada; al reconectar se restaura access token antes de WorkManager.
- Package + ACK actualizan Room en una transacción y Hoy observa disponibilidad sin pull manual; start crea draft/sets/operación local aun sin red.
- El start offline confirma en una sola transacción draft, sets, hash final, START pendiente y delivery `started_pending`; la recuperación acepta esa evidencia local sin exigir `started` remoto.
- Los aislamientos reales tienen motivo sanitizado y pantalla terminal sin spinner; revalidar el mismo fallo no vuelve a escribir Room ni realimenta el observer.
- La sesión local abre inmediatamente con scope, dispositivo, cuenta Room y refresh cifrado coherentes. Fallos temporales preservan la sesión; invalidez definitiva/revocación confirmada la limpia.
- Autosave usa debounce de 400 ms y flush en foco, navegación, pausa, completion y background. El autosync usa trabajo único, foreground/reconexión/eventos y single-flight real.

## Trabajo en curso

- Ejecutar instrumentación únicamente en un AVD separado y completar QA manual de agenda, package revision, offline/process death/reconexión, rotación, fuente grande, TalkBack y temas.
- El mapa canónico de documentos sigue siendo `DOCUMENTATION_INDEX.md`; este handoff no sustituye contratos ni historia.

## Decisiones activas

- Stack: JDK 17, compile/target SDK 36, min SDK 26, AGP 8.13.2, Gradle 8.13 y Kotlin 2.3.21.
- La base local usa `account_scope` derivado del servidor y usuario; ninguna consulta confía en un `user_id` recibido del cliente.
- El access token solo vive en memoria y el refresh token se cifra mediante Android Keystore AES-GCM.
- Packages se verifican por SHA256 antes de persistir; drafts y operaciones FIFO estrictas son durables. START bloquea PROGRESS/COMPLETE mientras esté en backoff o conflicto. El cursor avanza en la misma transacción Room que sus cambios.
- HTTPS es obligatorio salvo opt-in explícito para HTTP local en debug.
- Reloj, Bluetooth, telemetría continua, Play Store y firma de producción siguen fuera de alcance.

## Bloqueadores y riesgos

- Tras `adb install -r`, el borrador heredado actual no pudo recuperarse: conserva sets pero falla `draft_payload_hash_mismatch`. Quedó intacto y visible como aislamiento terminal, con 0 pendientes y 1 conflicto; no se recalculó el hash ni se descartó.

- Solo existe el AVD `Pixel_7`, reservado para QA manual; `connectedDebugAndroidTest` no se ejecutó para no borrar su identidad ni Room/DataStore.
- Persisten como QA manual: download→modo avión→start→process death→completion→reconexión, rotación, tamaños 320/360/411/600 dp, fuente grande, TalkBack, claro/oscuro y HTTPS.
- Lint conserva avisos no bloqueantes de versiones disponibles, KAPT/KSP y cleartext intencional exclusivo de debug. No se creó baseline ni supresión global.
- No debe declararse Alpha 1.2 lista para release hasta ejecutar instrumentación separada, revisión de integración y proceso de firma aprobado.

## Siguiente paso

Crear o disponer de un AVD de pruebas inequívocamente separado, ejecutar `connectedDebugAndroidTest` allí y completar el QA manual restante. Después realizar revisión de integración y el flujo aprobado de commit/push/merge/tag.

No se realizó commit, push, merge ni tag.

## Pruebas relevantes

- `lintDebug`: pasa.
- `testDebugUnitTest`: 49 tests, 0 fallos, pasa en dos ejecuciones consecutivas y forzadas.
- `assembleDebug`: pasa.
- `compileDebugAndroidTestKotlin`: pasa.
- `connectedDebugAndroidTest`: pendiente por falta de AVD separado; no se usó el Pixel_7 manual.
- `python -m compileall -q app tests`: pasa.
- Backend completo: local 600 tests pasan/3 omitidos en 127.48 s; Docker con las carreras MariaDB activas 602 pasan/1 omitido en 106.81 s. Ambas pasadas conservan 1 aviso conocido de fixture ZIP.
- Migración `20260724_0030`: single head, `db check` y ciclo upgrade/downgrade/upgrade pasan en MariaDB 11.4 efímero con `tmpfs`; la migración Room 2→3 preserva las tablas anteriores.
- `docker compose config --quiet`: pasa.
