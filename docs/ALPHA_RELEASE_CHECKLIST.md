# Checklist de release alpha privada

## Alpha 1.4 — Registro Diario de Salud Android

- [x] Resumen diario local-first con fecha/zona, peso, nutrición, pasos y entrenamiento.
- [x] CRUD owner-only de cuerpo, nutrición, alimentos personalizados y pasos con UUID, idempotencia y revisión.
- [x] Room 4 aislada por `accountScope`, migraciones explícitas 1/2/3→4 y sin fallback destructivo.
- [x] Operaciones offline durables, coalescing seguro, autosync WorkManager y process-death recuperable por persistencia Room.
- [x] Conflictos sanitizados visibles con usar servidor, reintentar, duplicar cuando aplica y cancelar.
- [x] Progreso Salud con peso, pasos, calorías/macros y alternativa textual accesible.
- [x] Backend completo: 612 pasan y 1 omitida en contenedores efímeros; schema/compileall/single head/db check/ciclo 0031 verdes.
- [x] Android: lint, dos pasadas JVM, APK y compilación de androidTest verdes.
- [ ] Ejecutar `connectedDebugAndroidTest` únicamente en AVD de pruebas separado.
- [ ] Completar QA manual offline/process death/reconexión, web↔Android, accesibilidad, rotación, temas y tamaños.
- [ ] Revisión de integración, firma y decisión formal de release.
- [ ] Alpha 1.4 lista para release: **NO**, hasta cerrar QA manual, instrumentación y firma aprobada.

## Alpha 1.3 — Planificación, Rutinas y Calendario Android

- [x] Catálogo owner-only paginado por nombre/alias y ausencia honesta de filtros no disponibles.
- [x] Rutinas/entrenamientos versionados con revisión optimista, idempotencia, rollback y proyección de imports/restores.
- [x] Programación por fecha/timezone reutiliza `PlannedWorkout`, Companion Delivery y el cursor existente.
- [x] Agenda semanal/mensual local-first; mover conserva UUID y crear/mover/cancelar consolida operaciones seguras sin romper FIFO.
- [x] Room 3 preservador y aislado; planificación offline-first, FIFO y conflictos sin last-write-wins.
- [x] Navegación Hoy/Plan/Historial/Progreso/Ajustes, editores con autosave y agenda semanal/mensual.
- [x] Prescripciones aditivas: doce modos, carga, RIR/RPE, descanso, tiempo, distancia y notas.
- [x] Hoy refleja Room inmediatamente; completion offline aparece una vez en Historial y actualiza Progreso local antes de reconciliarse.
- [x] Delivery/package es determinista por revisión; una descarga obsoleta puede reemplazarse sin mutar un draft activo.
- [x] Conflictos de revisión, archivo, ausencia, fecha y package muestran resolución explícita; archivo bloqueado con programaciones activas y restauración soportada.
- [x] Matriz final: lint sin errores, dos pasadas forzadas de 49 JVM, APK y androidTest compile; backend local 600/3 y Docker/MariaDB 602/1, compileall, 30 schemas, ciclo MariaDB 0030 y Compose config.
- [ ] QA manual visual, offline/process death/reconexión, package revision, rotación, tamaños, fuente grande, TalkBack, claro/oscuro y HTTPS en AVD/dispositivo separado.
- [ ] Alpha 1.3 lista para release: **NO**, hasta cerrar QA manual, instrumentación y firma aprobada.

## Alpha 1.2 — Historial y Progreso Android

- [x] API móvil owner-only con historial por cursor, filtros y detalle sin N+1.
- [x] Resumen 7/30/90/180/365/todo, ejercicios, puntos y comparación sin porcentaje engañoso con base cero.
- [x] Volumen y mejores marcas deterministas solo para modos de carga comparables; ausencia explícita para modos mixtos.
- [x] Room 2 por cuenta, migración preservadora, páginas/detalle/progreso estructurados y reconciliación por evento.
- [x] Navegación Hoy/Historial/Progreso/Ajustes, filtros, paginación, detalles y gráficas Canvas con fallback textual.
- [x] Integración con completion, pull, foreground, conectividad, WorkManager y single-flight existentes.
- [x] Ejecutar y registrar `lintDebug`, dos pasadas JVM (39 tests), `assembleDebug` y `compileDebugAndroidTestKotlin` finales.
- [x] Ejecutar y registrar compileall, suite backend completa (593 pasan, 3 omitidos) y `docker compose config --quiet` finales.
- [ ] QA manual visual, offline, accesibilidad y matriz de tamaños; no aprobado en esta rama.

## Alpha 1.1 — Android Companion

- [x] Proyecto Android Kotlin/Compose, wrapper fijado, variantes debug/release y CI sin publicación de artefactos.
- [x] Login/refresh/logout/revocación, Keystore, redacción y política HTTPS con excepción local solo debug.
- [x] Negociación 1.0, bootstrap, package SHA256, ACK/start/progress/complete/abort/fail.
- [x] Room aislado por cuenta, drafts, cola FIFO, cursor transaccional, backoff y WorkManager.
- [x] Package+ACK habilitan start local inmediato; start offline y cola `START → PROGRESS → COMPLETE` no requieren pull manual.
- [x] Sesión local elegible abre cache offline; refresh temporal conserva Keystore/scope y revocación confirmada limpia la sesión.
- [x] Autosave de campos con debounce/flush y autosync por eventos, foreground, conectividad y trabajo único coalescido.
- [x] Ejecución desde teléfono, historial, ajustes, tema y doce modos de carga con `BigDecimal`.
- [x] Pruebas unitarias/instrumentadas y workflow Android definidos en código.
- [x] Compilar `lintDebug testDebugUnitTest assembleDebug` con JDK 17 y Android SDK 36; pruebas JVM repetidas sin dependencia de orden/estado.
- [x] Compilar `compileDebugAndroidTestKotlin` con las pruebas Room/MockWebServer/Compose actuales.
- [ ] Ejecutar pruebas instrumentadas y validar migración Room en emulador/dispositivo.
- [ ] QA real offline/reinicio/rotación/accesibilidad/tema claro-oscuro y servidor HTTPS.
- [ ] Revisar firma, minificación, secretos y producir APK de release mediante proceso aprobado.
- [ ] Alpha 1.1 lista para release: **NO**, hasta cerrar los cuatro gates anteriores.

## Alpha 1.0 — Web Daily Driver

- [x] Onboarding derivado, preferencias owner-only y dashboard centrado en hoy.
- [x] Navegación consolidada, ayuda, rutina guiada/duplicación, agenda e historial filtrables.
- [x] Captura plegable con accesos a ejercicios; drafts, CSRF, idempotencia y cargas se conservan.
- [x] `/imports` unifica la entrada y delega en servicios existentes con preview/confirmación/auditoría.
- [x] PWA mínima sin cache de datos autenticados y guías de usuario.
- [x] Suite completa Docker/MariaDB después del último cambio: `579 passed, 1 skipped, 1 warning`.
- [x] Suite completa local después del último cambio: `577 passed, 3 skipped, 1 warning`.
- [x] Ciclo upgrade/downgrade/upgrade de `20260717_0028`, single head y `db check`.
- [x] QA manual real oscuro en 360/390/430/768/1024/1366 px, sin overflow ni consola.
- [ ] Sign-off visual real en tema claro; el navegador QA no ofrece emulación.
- [x] Logs, restart/persistencia y dry-runs finales; solo permanece el warning seguro de clave API no separada.
- [ ] Rotar la credencial cuyo material codificado apareció durante la recuperación del QA antes del release.

## Alpha 0.9 — Workout Load Entry

- [x] Doce modos explícitos, `Decimal`, kg/lb mixtos y `calculation_version` canónico.
- [x] Perfiles/última carga owner-only, draft, CSRF recovery, idempotencia y edición segura.
- [x] Import/export, backup/restore, Mobile Sync y Companion aditivos.
- [x] Migración 0027 reversible en SQLite y MariaDB aislados; sesiones heredadas intactas.
- [x] Suites local/Docker, QA HTTP, restart, logs y dry-runs limpios.
- [x] Responsive real oscuro a 360/390/430/768/1024/1366 px.
- [ ] Sign-off visual real en tema claro; el navegador de QA no ofrece emulación.

## Alpha 0.8.1 — Workout Session Recovery

- [x] Recuperación específica de CSRF con token nuevo y campos preservados.
- [x] Borrador local y servidor owner-only con expiración, revisión y límites.
- [x] `client_submission_id` y constraint único por usuario.
- [x] Sesión, planned workout, sync y eliminación del draft forman un commit atómico.
- [x] Export/restore conservan el identificador web sin cambiar Mobile Sync.
- [x] Migración 0026 reversible en ciclos aislados SQLite y MariaDB 11.4; single head y db check limpios.
- [x] Suite completa local y Docker final; concurrencia MariaDB incluida.
- [x] QA manual móvil oscuro, reinicio, persistencia y logs.
- [ ] Sign-off visual real en tema claro; el navegador de QA actual no ofrece emulación.
- [x] P1 captura avanzada de cargas implementada en `feature/workout-load-entry`; su publicación depende de los gates Alpha 0.9.

## Alpha 0.8 — Companion Backend Foundation

- [x] Perfil persistente y negociación allowlisted 1.0.
- [x] Package inmutable con hash y campos descartados explícitos.
- [x] Delivery persistente, ACK, start, abort, fail y estados terminales.
- [x] Checkpoints pequeños, secuencia e idempotencia.
- [x] Completion reutiliza `TrainingSession` y Mobile Sync atómicamente.
- [x] Schemas, CLI y UI homelab mínima.
- [x] Suite local y Docker finales verdes.
- [x] Upgrade/downgrade/upgrade y single head `20260714_0025` verificados.
- [x] QA manual HTTP y persistencia tras restart.
- [ ] Sign-off visual humano completo de planned workouts/companion: oscuro verificado en seis anchos; claro pendiente por falta de emulación disponible.
- [ ] APK/reloj/Bluetooth/telemetría continua (fuera de alcance).

## Alpha 0.7 — Mobile Sync Foundation

- [x] PlannedWorkout persistente con snapshot y versión histórica.
- [x] Completed workout API sobre TrainingSession.
- [x] Bootstrap, pull, push y status.
- [x] Revisiones, conflictos, tombstones e idempotencia.
- [x] UI web mínima y cleanup CLI.
- [x] Suites SQLite y MariaDB verdes; concurrencia MariaDB probada.
- [ ] Recorrido visual manual final en navegador.
- [ ] APK companion (fuera de alcance).
- [ ] Watch bridge (fuera de alcance).

## Alpha 0.6 — API Auth Foundation

- [x] Suite local y Docker verde.
- [x] Migraciones `20260713_0021` y `20260713_0022`: upgrade/check y downgrade/upgrade temporal.
- [x] Login, refresh/reuse, logout-all, dispositivos y restart QA.
- [x] `/me`, bootstrap y rutina activa owner-only.
- [x] CORS cerrado y logs sin secretos.
- [x] Sync Fase 7B confirmado unsupported.

## Alpha 0.6.1 — Web UI Homelab

- [x] Navegación lateral agrupada y ruta activa clara en escritorio.
- [x] Menú móvil cerrado por defecto y usable a 360/390/430 px.
- [x] Dashboard diario aparece antes del onboarding.
- [x] `/account/system` muestra estado seguro sin secretos ni paths.
- [x] `/account/devices` lista solo dispositivos propios y revoca por POST + CSRF.
- [x] Formularios tienen controles táctiles, foco visible y labels asociados.
- [x] Tablas anchas desplazan solo dentro de su wrapper.
- [x] Tema claro y oscuro del sistema mantienen contraste legible.
- [x] No existe scroll horizontal global en 360/390/430/768/1024/1366 px.
- [x] Suite local, suite Docker y `flask db check` verdes.

Usa esta lista antes de invitar a un compañero real a una alpha por LAN/VPN.

## Instalación y migraciones

- [ ] `git status --short --branch` muestra la rama esperada.
- [ ] `.env` existe localmente, no se comparte y no contiene placeholders.
- [ ] `docker compose config --quiet` pasa.
- [ ] `docker compose up --build -d` levanta `web` y `db`.
- [ ] `docker compose exec web flask db upgrade` termina sin error.
- [ ] `docker compose exec web flask db check` dice `No new upgrade operations detected`.
- [ ] `/healthz` responde `status: ok`.

## Admin y cuenta de compañero

- [ ] Admin puede iniciar sesión.
- [ ] Admin abre `/admin/users`.
- [ ] Admin crea un segundo usuario con rol `user`.
- [ ] Email duplicado se rechaza con mensaje claro.
- [ ] El nuevo usuario inicia sesión desde navegador normal.
- [ ] Usuario normal no puede abrir `/admin/users` ni `/admin/system`.

## Primer acceso

- [ ] Dashboard vacío responde 200.
- [ ] Se ve aviso de `Alpha 0.5`.
- [ ] Se ve aviso de que no sustituye atención médica.
- [ ] Se ve checklist de primeros pasos.
- [ ] La navegación funciona en ancho móvil.
- [ ] `/privacy` explica almacenamiento, export y alcance LAN/VPN.

## Capturas mínimas

- [ ] Usuario registra peso manual.
- [ ] Usuario registra energía manual.
- [ ] Usuario registra nutrición manual.
- [ ] Usuario registra una sesión de entrenamiento basada en rutina propia.
- [ ] Cada guardado muestra éxito o error comprensible.
- [ ] Después de capturar, el dashboard muestra datos actualizados.

## Importación y auditoría

- [ ] `/imports/standard` abre para usuario autenticado.
- [ ] `/imports/files` abre para usuario autenticado.
- [ ] Preview de JSON válido no escribe datos.
- [ ] Preview de FIT/GPX/TCX/CSV válido no escribe datos de dominio.
- [ ] Confirmación explícita guarda datos.
- [ ] Reimportar el mismo FIT/GPX/TCX/CSV devuelve `skip` o duplicado esperado, no inserta copias.
- [ ] `/imports/history` muestra el run agregado.
- [ ] `/imports/history/<id>` muestra hashes truncados y no payload crudo.
- [ ] Token inválido o plan conflictivo no crea datos de dominio.

## Export y aislamiento

- [ ] Usuario descarga `/account/export.json`.
- [ ] Export no incluye `password_hash`, tokens ni archivos binarios.
- [ ] Segundo usuario no ve peso, energía, nutrición, sesiones, imports ni exports del primero.
- [ ] IDs ajenos responden 404 o 403 según ruta.
- [ ] `/exports` muestra solo artefactos del usuario autenticado.
- [ ] Preview de export no crea archivo ni `ExportRecord`.
- [ ] Confirmación genera archivo, SHA256 y registro owner-only.
- [ ] Activity y Route descargan JSON/CSV/GPX/TCX según capability.
- [ ] Rutina y sesión descargan PDF válido; ZWO/ERG/MRC rechazan planes incompatibles.
- [ ] Archivo faltante o alterado no se descarga.

## Backup integral y recuperación

- [ ] `/account/backups/new` muestra preview antes de crear el ZIP.
- [ ] El backup contiene un único `manifest.json` y `account/user_data_export.json`.
- [ ] Raw uploads y exports generados incluidos coinciden por tamaño y SHA256.
- [ ] `/account/backups/restore` valida sin escribir datos ni storage final.
- [ ] Confirmación restaura datos y archivos con ownership del usuario autenticado.
- [ ] Repetir el mismo backup produce skips y no duplica archivos.
- [ ] Otro usuario no puede ver ni descargar el backup, raw o generated restaurados.
- [ ] `flask backup reconcile` corre en dry-run y no modifica registros.

## Logout y persistencia

- [ ] Logout se hace por POST con CSRF desde navegación.
- [ ] Después de logout, dashboard redirige a login.
- [ ] Reiniciar `web` conserva login/data en DB.
- [ ] Reiniciar `db` sin borrar volúmenes conserva datos.
- [ ] `docker compose down` y `docker compose up -d` conservan datos.
- [ ] No se usa `docker compose down -v`.

## Validación técnica

- [ ] `.\.venv\Scripts\python.exe -m compileall -q backend`
- [ ] `.\.venv\Scripts\python.exe -m pytest backend/tests/ -q`
- [ ] `docker compose exec -T web flask db check`
- [ ] Si se instala pytest temporalmente en Docker, queda documentado.
- [ ] `git diff --check` limpio.
- [ ] No hay archivos temporales ni cambios en `/data`, `.env`, schemas públicos o migraciones innecesarias.

## Decisión

La alpha privada está lista si:

- [ ] No hay bloqueantes de login, captura, dashboard, export o logout.
- [ ] El aislamiento por usuario está probado.
- [ ] Hay un procedimiento claro de acceso LAN/VPN.
- [ ] Admin sabe crear y entregar cuentas.
- [ ] La suite local y Docker están verdes.
