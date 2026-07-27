# Handoff activo

## Estado actual

- Alpha 1.5 Health Connect de solo lectura está implementada en `feature/alpha-1.5-health-connect`, iniciada en `1b1afba17ae2e7e27ed88fe495230d06f8d2865a`. No realizar commit, push, merge ni tag desde este handoff.
- Android es `1.5.0-alpha01` y usa `androidx.health.connect:connect-client:1.1.0` sin cambiar AGP, Gradle, SDK ni JDK 17.
- `HealthConnectGateway`, manager, coordinator y fake aíslan el SDK. Hay disponibilidad API 26–36, permisos por tipo, background por feature, páginas, aggregate, Changes, token expirado, single-flight y WorkManager coalescido.
- Se importan peso, grasa enlazada por instante/origen, pasos `COUNT_TOTAL` por día/zona y nutrición opt-in representable. Masa magra/agua permanecen deshabilitadas por incompatibilidad semántica. No existe escritura hacia Health Connect.
- Room 5 añade settings, permisos, sync state y ledger por `accountScope`, procedencia en Hoy/Progreso, dedupe, borrados y `detached/user_override`; migraciones explícitas 1/2/3/4→5.
- El backend añade migración `20260726_0032`, fuentes Health Connect y `client_event_id` owner-scoped para cuerpo, nutrición y pasos. Manual y Health Connect coexisten; pasos manuales conservan precedencia visual.
- Ajustes ofrece selección, conectar, administrar acceso, sync, background, pausa, desconexión y borrado selectivo confirmado. No se registran valores, IDs/origins completos, permisos, tokens ni payloads.
- Los gates finales están verdes: Android lint, 84 JVM sin fallos en dos ejecuciones reales, APK y compilación androidTest; backend `612 passed, 3 skipped`; MariaDB 11.4 efímera con upgrade/check/downgrade/re-upgrade y 3 carreras concurrentes; 36 JSON, manifest, Compose config y `git diff --check` validados.

## Base preservada

- Alpha 1.4 conserva resumen/progreso, cuerpo, nutrición, catálogo y pasos owner-only; Room 4 y migración backend `20260726_0031`; su cierre fue backend `612 passed, 1 skipped` en MariaDB efímera y Android 53/53, lint, APK y androidTest compile.
- Alpha 1.3 conserva catálogo, planes/versiones, agenda, schedule/move/cancel, packages por revisión, conflictos y completion local en Historial/Progreso.
- Alpha 1.2 conserva historial/progreso estructurado, reconciliación por `client_event_id`, cache offline y recuperación de process death.
- Alpha 1.1 conserva login/API Auth, Companion Delivery, ejecución offline, drafts, FIFO y autosave. Un draft QA heredado sigue aislado por `draft_payload_hash_mismatch`; no se recalculó ni descartó.

## Trabajo en curso

- Ejecutar QA manual Alpha 1.5 solo con datos ficticios y en AVD/dispositivo separado: proveedor, permisos parciales/revocados, dedupe/borrados, zona, background, servidor offline, process death, selective delete, rotación, tamaños, fuente grande, TalkBack y temas.
- El mapa canónico sigue siendo `DOCUMENTATION_INDEX.md`; este handoff no sustituye schemas, pruebas ni reglas.

## Decisiones activas

- Stack: JDK 17, compile/target SDK 36, min SDK 26, AGP 8.13.2, Gradle 8.13 y Kotlin 2.3.21.
- Room y toda consulta sensible se particionan por `accountScope`; el owner real siempre deriva del servidor/Bearer, nunca de un `user_id` del cliente.
- Health Connect es opt-in, read-only y Room-first. Tokens por cuenta/tipo/generación; cambiar permiso invalida solo su tipo. Manual tiene precedencia visual y una edición separa la copia del origen.
- Access token solo en memoria; refresh cifrado con Android Keystore. HTTPS salvo opt-in HTTP local debug. Packages SHA256, drafts y cola FIFO siguen durables.
- Reloj, BLE, fabricantes directos, escritura Health Connect, ejercicio/rutas, sueño, signos vitales, datos médicos, Play Store y firma de producción quedan fuera de alcance.

## Bloqueadores y riesgos

- `connectedDebugAndroidTest` no se ejecutó: el único AVD está reservado para QA manual y no debe limpiarse. Las migraciones instrumentadas solo están compiladas.
- La conducta real de proveedores, background, revocación y atribución sintética Health Connect requiere QA manual; el fake no sustituye esa evidencia.
- Lint conserva avisos no bloqueantes conocidos de toolchain/cleartext debug; no se creó baseline ni supresión global.
- Alpha 1.5 no está lista para release hasta instrumentación separada, QA, revisión de integración y firma aprobada.

## Siguiente paso

Finalizar los gates técnicos y después usar un AVD/dispositivo de pruebas inequívocamente separado para instrumentación y QA Health Connect. No usar ni limpiar el AVD manual reservado.

No se realizó commit, push, merge ni tag.

## Pruebas relevantes

- Android: `lintDebug`, `assembleDebug` y `compileDebugAndroidTestKotlin` pasan; `testDebugUnitTest` registra 84/84, incluida la matriz Health Connect de 31 casos, y pasó una segunda ejecución forzada.
- Room: schema 5 exportado; pruebas de migración 1/2/3/4→5 compilan. `connectedDebugAndroidTest` permanece pendiente.
- Backend: `compileall` y suite completa pasan con `612 passed, 3 skipped`; Compose con `.env.example` es válido.
- MariaDB 11.4 efímera: migraciones hasta 0032, `db check`, downgrade 0032→0031, re-upgrade y 3 pruebas de concurrencia pasan; contenedor/red se eliminaron y no se montó almacenamiento persistente.
- Contratos: 36 JSON parsean, Room schema 5 está exportado, merged manifest contiene únicamente los permisos Health Connect documentados y `git diff --check` pasa.
