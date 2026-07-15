# Handoff activo de Health Tracker

## Actualización 2026-07-14 — Fase 7C / Alpha 0.8

- Rama: `feature/phase-7c-companion-delivery`.
- Base verificada: `b0b6bb2`, tag exacto `alpha-0.7-mobile-sync`; `master` y `origin/master` coincidían y el árbol inicial estaba limpio.
- Alpha 0.7 integrada: planned workouts, completed upload, sync bootstrap/pull/push/status, revisiones, tombstones, cursor, idempotencia, cleanup y UI mínima; head previo `20260714_0023`.
- Implementación activa: perfil/negociación companion 1.0, package/hash, delivery persistente, ACK/start/abort/fail, checkpoints, completion reutilizando `TrainingSession`, schemas, CLI y UI homelab.
- Migraciones nuevas: `20260714_0024_companion_delivery.py` y `20260714_0025_companion_profile_cascade.py`; la segunda corrige en sitio la política FK sin borrar filas.
- Validación final: específica `51 passed, 2 skipped`; local completa `535 passed, 2 skipped, 1 warning`; Docker/MariaDB `536 passed, 1 skipped, 1 warning`. El único skip Docker es `test_active_handoff.py` porque `docs/` no se copia a la imagen; el warning es el ZIP duplicado intencional de backup.
- No implementado: APK, reloj, Bluetooth, telemetría continua, FIT output, vendors, CRDT ni sync write de wellness/labs/activity/route.
- Migraciones: single head `20260714_0025`; MariaDB upgrade/check limpios. Ciclo SQLite temporal `0023 -> 0024 -> 0025 -> 0024 -> 0025` y `db check` limpio. El historial SQLite completo sigue bloqueado por la incompatibilidad preexistente de `0015`.
- QA HTTP: negociación, delivery/package, ACK/start/checkpoint, replay, conflicto de secuencia, completion idempotente, persistencia tras restart y revocación pasaron sin imprimir tokens.
- QA visual real: `/planned-workouts` y `/account/devices` revisados a 360/390/430/768/1024/1366 px en tema oscuro, sin overflow global, con perfil/versiones/features/deliveries, acción owner-only y CSRF. El navegador disponible no permitió emular tema claro; esa comprobación visual sigue pendiente y no debe marcarse como realizada.
- Riesgos: rate limiter por proceso; retención de perfiles/terminales report-only; incompatibilidad histórica SQLite de `0015`; tema claro pendiente de sign-off visual real.
- Siguiente acción: revisión final del diff y sign-off visual de tema claro antes de decidir release/integración de Alpha 0.8.

Reglas: [`project-rules/companion-protocol.md`](project-rules/companion-protocol.md), [`project-rules/api-v1.md`](project-rules/api-v1.md) y [`project-rules/mobile-sync.md`](project-rules/mobile-sync.md). Este handoff no reemplaza schemas ni tests.

## Actualización 2026-07-14 — Fase 7B

- Rama: `feature/phase-7b-mobile-sync`.
- Base: `1da7e13`, tag `alpha-0.6.1-web-ui-homelab`.
- Baseline previa: `513 passed` local.
- Migración aditiva: `20260714_0023_mobile_sync.py`.
- Push soportado: `planned_workout`, `completed_workout`.
- No implementado: APK, reloj, CRDT, push de wellness/labs/activity/route.
- Resultado local: `522 passed, 1 skipped`; el skip es la prueba de concurrencia MariaDB, ejecutada solo en Docker.
- Resultado Docker: `522 passed, 1 skipped`; el skip es `test_active_handoff.py` porque `docs/` no se copia a la imagen.
- MariaDB: idempotency-key, client-operation y revision race verificados.
- `flask db check`: limpio. `git diff --check`: limpio.
- Pendiente de release: recorrido visual manual en navegador; el controlador local no permitió abrir `localhost` durante este bloque.

Regla canónica: [`project-rules/mobile-sync.md`](project-rules/mobile-sync.md). Este handoff es temporal y no puede contradecir schemas, tests ni reglas canónicas.

## 2026-07-13 — Alpha 0.6.1 Web UI Homelab

- Rama `feature/phase-web-ui-homelab`; base `e998979`, tag exacto `alpha-0.6-api-auth`.
- Árbol inicial limpio y sincronizado con `master`/`origin/master`.
- Objetivo: consolidar la UI Flask/Jinja/CSS para escritorio y móvil sin cambiar contratos de backend.
- Implementado: shell autenticado, navegación agrupada, menú móvil nativo, tema del sistema, dashboard orientado al día, operación reciente, `/account/system` y `/account/devices` owner-only.
- Seguridad: revocación de dispositivo por POST + CSRF; no se muestran tokens, secretos, paths internos, logs ni datos de otros usuarios.
- Modelos, schemas y migraciones: sin cambios.
- Regla canónica: `project-rules/web-ui.md`; guías: `WEB_UI_HOMELAB.md`, `WEB_UI_DESIGN_SYSTEM.md` y `WEB_UI_ACCESSIBILITY.md`.
- Validación final: local `513 passed`; Docker `512 passed, 1 skipped`. El skip exacto es `tests/test_active_handoff.py` porque `docs/` no se copia a la imagen. `compileall`, `docker compose config`, head/upgrade y `flask db check` limpios.
- QA visual: login/logout, dashboard, módulos principales, 404, dispositivos y estado homelab revisados; sin overflow global a 360/390/430/768/1024/1366 px. Menú móvil cerrado por defecto y sesión persistente después de reiniciar `web`.
- Bug corregido: mojibake visible preexistente en actividad, rutas e imports; el escaneo de templates y el DOM final quedan limpios.
- Riesgos: el tema sigue la preferencia del sistema y no tiene toggle persistente; no se realizó auditoría formal con lector de pantalla; el status homelab es diagnóstico ligero, no monitoreo de infraestructura.
- Siguiente acción: revisar el diff y decidir integración; no se hizo commit, push, merge ni tag.

Este bloque reemplaza como estado temporal a las secciones históricas que siguen, pero no reemplaza schemas, tests, `AGENTS.md` ni reglas canónicas.

## 2026-07-13 — Fase 7A

- Rama `feature/phase-7a-api-auth`; base `7916cde`, tag `alpha-0.5-full-backup-recovery`.
- Nueva API `/api/v1`, sesiones/dispositivos, access/refresh y migraciones `20260713_0021`/`0022`; la segunda persiste UUID públicos de usuario/rutina/versión.
- Validación final: local `507 passed`; Docker `506 passed, 1 skipped` (`test_active_handoff.py`, porque `docs/` no entra en la imagen).
- Migraciones `20260713_0021`/`0022`: MariaDB en head con upgrade/check limpios; downgrade/upgrade aislado de `0022` limpio en SQLite temporal y backfill UUID verificado.
- QA HTTP: login, `/me`, devices, bootstrap, rutina y refresh 200; sin Bearer 401; dos refresh simultáneos en MariaDB producen exactamente un 200/un 401, un solo sucesor y revocación de familia; token persiste tras restart; revocar dispositivo invalida access.
- Sin sync Fase 7B, planned workouts, APK o reloj.
- Riesgos: rate limit por proceso/no global; no hay rutina global activa y se declara `most_recent_plan_active_version`.

Leer `../AGENTS.md`, `AI_WORK_CONTEXT.md` y `project-rules/api-v1.md`. Sustituir este bloque por resultados exactos al cerrar.

Documento temporal para retomar el proyecto sin memoria previa.

Ultima actualizacion: 2026-07-13.

## Estado vigente de Fase 6B

- Rama: `feature/phase-6b-full-backup-recovery`.
- Base/tag verificados: `f36ae9d`, `alpha-0.4-exporters-complete`.
- Árbol inicial: limpio y sincronizado con `master`/`origin/master`.
- Objetivo: Alpha 0.5, backup integral ZIP y recuperación de datos + binarios.
- Baseline previa: `441 passed` local, `440 passed, 1 skipped` Docker.
- Resultado local actual: `475 passed` (10 nuevas pruebas de orphan_details).
- Resultado Docker final: `464 passed, 1 skipped`; skip exacto `tests/test_active_handoff.py` porque `docs/` no se copia a la imagen.
- MariaDB: head `20260712_0020`, upgrade y `flask db check` limpios.
- QA manual: backup A ZIP 1.0 creado/descargado, manifest inspeccionado, restore en cuenta QA B confirmado, reimport con 0 file inserts/31 skips, aislamiento 404, raw/generated descargables y persistentes tras restart; móvil 360/390/430 sin overflow global.
- Reconcile dry-run: DB/files registrados íntegros, sin staging ni pending abandonado; reportó 2 archivos finales huérfanos preexistentes y no los modificó.
- Ajuste orphan_details (2026-07-13): dry-run ahora muestra bloque de metadata allowlisted por cada huérfano; `--apply` no toca huérfanos finales; 10 pruebas nuevas cubren raw/generated/orden/no-path-absoluto/no-original_filename/no-contenido/vanished/dry-run-no-modifica/apply-no-elimina/zero-orphans.
- Migraciones nuevas: ninguna; head sigue `20260712_0020`.
- Contrato nuevo: `schemas/full_backup_manifest.schema.json`, `backup_format_version=1.0`.
- Servicios: `AccountBackupService`, `BackupArchiveReader`, `BackupRestoreCoordinator` y `BackupReconciliationService`.
- Rutas: `/account/backups`, `/account/backups/new`, detalle/download, `/account/backups/restore` y confirmación.
- Regla canónica: `project-rules/full-backup.md`.
- No se tocó `.env`, `/data` manualmente ni se usaron datos reales. No se hizo commit ni push.

Los dos archivos finales huérfanos reportados por reconcile son clasificados como `legacy_upload` y/o `legacy_generated`; solo se reportan, no se eliminan automáticamente. Investigar antes de borrar manualmente.


Las secciones históricas de Alpha 0.4 que siguen a continuación explican la base. Si contradicen este bloque, manda esta sección, schemas, tests y reglas canónicas.

Este handoff no reemplaza:

- `../AGENTS.md`
- `AI_WORK_CONTEXT.md`
- `docs/PROJECT_CONTEXT.md`
- `project-rules/canonical-data-contract-import-update.md`
- `project-rules/phase-5b-universal-json-import-assistant.md`
- `project-rules/standard-json-generator-development.md`
- `project-rules/confirmed-standard-import.md`
- `project-rules/account-restore.md`
- `ACCOUNT_RESTORE.md`
- `DATA_PORTABILITY.md`

Si contradice schemas, tests, codigo o reglas canonicas, este archivo pierde prioridad.

## Bloque activo

- Rama de trabajo: `feature/phase-6-exporters-complete`.
- Base efectiva verificada: `2d617ed`.
- Base esperada por el usuario: `2d617ed`.
- Arbol antes del trabajo: limpio.
- Objetivo: Fase 6 / Alpha 0.4, exportadores avanzados y artefactos auditables.
- Se agrega el modelo aditivo `ExportRecord`, registry/capability, storage atómico generated, rutas `/exports` y formatos interoperables.
- FIT binario de entrada se conserva; FIT de salida queda unsupported experimental.
- No se tocó `.env` ni `/data`.
- No se hizo commit ni push.
- Regla fuerte: No tocar `/data`.

## Objetivo del bloque

Cerrar exportadores avanzados con trazabilidad:

```text
recurso owner-only -> capability/preview -> confirmación -> render -> storage atómico -> ExportRecord -> descarga verificada
```

## Estado actual del bloque

- Línea base limpia previa: `429 passed`.
- Registry con formatos por dominio y capability honesta.
- Activity/Route: JSON, CSV, GPX y TCX.
- TrainingPlan: JSON/CSV/HTML/PDF/ZWO/ERG/MRC, incluida versión histórica.
- TrainingSession: JSON/CSV/HTML/PDF.
- Storage generated con SHA256, tamaño, path relativo, owner y eliminación controlada.
- FIT output: unsupported experimental; FIT input se conserva.

- GPX: actividad si hay timestamps; ruta si no hay timestamps.
- TCX: actividad con laps/trackpoints básicos.
- CSV: pesajes y energía diaria.
- JSON: medical_lab, training_plan y completed_workout pasan por pipeline común si cumplen schema.
- FIT: decoder binario con `fitdecode`, actividad + ruta cuando hay GPS, actividad con warning cuando no hay GPS.

## Implementado en esta rama

- Modelo/migración aditiva `ExportRecord` (`20260712_0020`).
- Blueprint `/exports` con preview read-only, generación POST, historial, detalle, descarga y delete.
- Metadata allowlisted `export_records` en `user_data_export`; restore la trata como unsupported sin binario.

- Servicio `AccountRestoreService`.
- Rutas:
  - `GET /account/data`
  - `GET/POST /account/restore`
  - `POST /account/restore/confirm`
- Export completo ahora incluye seccion `recipes`.
- Restore merge seguro desde `user_data_export`.
- Remapeo en memoria de IDs antiguos a IDs del usuario autenticado para:
  - `training_plans`
  - `training_plan_versions`
  - `training_sessions`
- Auditoria saneada con `ImportRun.target_type = user_data_restore`.
- Data center de cuenta con export, restore, import estándar, historial y último audit run.
- Límites defensivos de JSON: tamaño, profundidad, nodos, arrays, strings, claves y secciones.
- Validación de schema version antes de schema general para rechazar exports futuros con mensaje claro.
- Token de restore ligado a versión, modo, usuario, schema, payload y plan; la web evita reutilización accidental por sesión.
- Recetas restauradas validan referencias a productos existentes o incluidos en el mismo export.
- Pruebas de round-trip, idempotencia, token manipulado/reutilizado, límites, referencias faltantes, flujo web y pantallas post-restore.

## Secciones del export y politica actual

| Seccion | Restore |
| --- | --- |
| `food_products` | insert/update/skip por nombre + marca |
| `recipes` | insert/update/skip por nombre; ingredientes por nombre/marca de producto |
| `weigh_ins` | insert/update/skip por usuario + fecha/hora + fuente |
| `daily_energy` | insert/update/skip por usuario + fecha |
| `daily_nutrition` | insert/update/skip por usuario + fecha |
| `medical_lab_reports` | insert/update/skip por usuario + fecha + laboratorio |
| `training_plans` | insert/skip/update por nombre y SHA de versiones |
| `training_sessions` | insert/skip; update inseguro sigue siendo conflicto |
| `activities` | insert/skip por fingerprint canónico |
| `routes` | insert/skip por fingerprint canónico |
| `daily_balances` | omitido, derivado |
| `uploads` | omitido, metadata sin binarios |

## Garantias vigentes

- El usuario/email/rol del export se ignoran.
- El `user_id` efectivo siempre proviene de la sesion autenticada.
- Preview no escribe DB ni guarda archivos.
- Confirmacion se firma contra usuario, modo, version, schema, payload y plan.
- Commit es atomico; ante error hace rollback.
- `pending` queda persistido antes de mutaciones de dominio y `failed` se escribe con transaccion limpia tras rollback.
- No se guardan payloads crudos, tokens, trazas ni datos sensibles en `ImportRun`.
- Restore no toca `/data` ni restaura archivos binarios.

## Riesgos y pendientes

- FIT de salida no tiene encoder mantenido configurado.
- GPX/TCX pueden perder metadata de dispositivo no interoperable; las pérdidas se declaran.
- ZWO/ERG/MRC solo representan un día con potencia explícita y no convierten fuerza.
- Backup ZIP/binarios sigue fuera de alcance (Alpha 0.5).

- No hay restore ZIP ni restore de binarios de uploads.
- No hay borrado masivo; el modo actual es merge.
- La equivalencia semantica round-trip ignora IDs, timestamps y derivados.
- `training_sessions` conserva update como conflicto salvo repeticion equivalente.
- Si se agregan nuevos dominios al export, deben añadirse explicitamente a restore y pruebas.
- `AccountRestoreService` sigue siendo un merge, no una sincronizacion espejo.
- La proteccion anti-replay de tokens es por sesion web; tokens viejos tambien se invalidan por expiracion y hash de payload/plan.
- Nota de compatibilidad con prueba historica: la frase `Restore/import real aún no existe` ya no describe este bloque para restore de `user_data_export`; sigue aplicando a restore ZIP/binarios.
- Nota de compatibilidad legacy: `Restore/import real aÃºn no existe`.

## Validacion esperada

Resultados de este bloque:

- Local: `441 passed`.
- Docker: `440 passed, 1 skipped`.
- Skip Docker esperado: `tests/test_active_handoff.py`, porque `docs/` no se copia a la imagen.
- MariaDB: head `20260712_0020`; `flask db check` limpio.
- SQLite aislado para `0020`: upgrade/downgrade/upgrade y `db check` limpios.
- QA web: PDF de rutina y sesión generados; historial persistió tras restart; Activity/Route mostraron formatos esperados; móvil 360/390/430 sin overflow global.

```powershell
& '.\.venv\Scripts\python.exe' -m compileall -q backend
& '.\.venv\Scripts\python.exe' -m pytest backend/tests/ -q
docker compose config --quiet
docker compose up --build -d
docker compose exec -T web flask db check
docker compose exec -T web python -m pytest -q
git diff --check
git diff --stat
git diff --name-status
git status --short --branch
```

Si pytest no esta instalado en la imagen:

```powershell
docker compose exec -T --user root web sh -lc "pip install --no-cache-dir -r requirements-dev.txt && python -m pytest -q -rs"
```

Skip Docker esperado si aparece: `tests/test_active_handoff.py`, porque `docs/` no se copia a la imagen de produccion.

## Siguiente accion concreta

1. Revisar el diff y la matriz final de Fase 6B.
2. Investigar por separado los 2 archivos huérfanos reportados por reconcile antes de cualquier borrado; no son records missing/corrupt.
3. No hacer commit ni push hasta instrucción explícita.
