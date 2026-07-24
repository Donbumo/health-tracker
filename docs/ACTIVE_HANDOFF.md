# Handoff activo

Actualizado: 2026-07-23.

## Estado actual

- Rama: `feature/alpha-1.1-android-companion`.
- Base comprobada al iniciar: `6b41d1c1d51850aa523bdc12cb8b41a5b0bc639e`; `alpha-1.0.1-runtime-security` es ancestro.
- El código fuente de Android Companion Alpha 1.1 está implementado en `../android/`: login, configuración segura de servidor, negociación, cache Room, ejecución desde teléfono, captura de cargas, cola offline, sync periódico y UI Compose.
- No se cambió persistencia backend ni hacen falta migraciones. `sync_pull.schema.json` recibió la corrección aditiva para `companion_profile` y `companion_delivery`, que el backend ya emitía.
- La persistencia de start/draft/set usa `Upsert` y transacciones; el caso QA `test1` fue recuperado como activo con pendientes/conflictos en cero sin borrar datos.
- Hoy, Entrenamiento, Historial y Ajustes representan estados humanos de conexión/sync/cola, protegen acciones repetidas y conservan la navegación hasta que complete/abort quedan durables.
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
- No debe declararse Alpha 1.1 lista para release hasta ejecutar instrumentación separada, revisión de integración y proceso de firma aprobado.

## Siguiente paso

Crear o disponer de un AVD de pruebas inequívocamente separado, ejecutar `connectedDebugAndroidTest` allí y completar el QA manual restante. Después realizar revisión de integración y el flujo aprobado de commit/push/merge/tag.

No se realizó commit, push, merge ni tag.

## Pruebas relevantes

- `lintDebug`: pasa.
- `testDebugUnitTest`: 35 tests, pasa en dos ejecuciones consecutivas.
- `assembleDebug`: pasa.
- `compileDebugAndroidTestKotlin`: pasa.
- `connectedDebugAndroidTest`: pendiente por falta de AVD separado; no se usó el Pixel_7 manual.
- Backend: intacto durante esta tanda; no se repitieron suites backend.
