# Checklist de release alpha privada

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
- [ ] P1 captura avanzada de cargas (fuera de este hotfix; `feature/workout-load-entry`).

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
