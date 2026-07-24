# Handoff activo

Actualizado: 2026-07-24.

## Estado actual

- Rama: `feature/alpha-1.2-mobile-progress`.
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

- Ejecutar instrumentación únicamente en un AVD separado y completar QA manual offline, rotación, fuente grande, TalkBack y temas.
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
- `testDebugUnitTest`: 39 tests, 0 fallos, pasa en dos ejecuciones consecutivas.
- `assembleDebug`: pasa.
- `compileDebugAndroidTestKotlin`: pasa.
- `connectedDebugAndroidTest`: pendiente por falta de AVD separado; no se usó el Pixel_7 manual.
- `python -m compileall -q app tests`: pasa.
- Backend completo: 593 tests pasan, 3 omitidos y 2 avisos no bloqueantes en 125.83 s.
- Migración `20260724_0029`: upgrade, backfill, restricciones únicas y downgrade pasan en SQLite aislado.
- `docker compose config --quiet`: pasa.
