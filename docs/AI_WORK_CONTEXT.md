# Contexto operativo para agentes de IA

## Bloque activo: Alpha 1.0 Web Daily Driver

Rama `feature/alpha-1.0-web-daily-driver`, base exacta `d2e804a`, tag `alpha-0.9-workout-load-entry`. Leer [`project-rules/web-daily-driver.md`](project-rules/web-daily-driver.md), [`USER_GUIDE.md`](USER_GUIDE.md) e [`IMPORT_HUB.md`](IMPORT_HUB.md) para cambios web. El bloque usa la migración aditiva `20260717_0028` para nombre visible, zona horaria y ocultamiento del onboarding.

Invariantes: `/imports` es la entrada visible, los adaptadores internos no se duplican, preview no escribe, el usuario proviene de la sesión y la PWA solo cachea `/static/`. No tocar `.env`, `/data` o el stack activo. No declarar Alpha 1.0 lista hasta tener suite local/Docker, migración y QA visual real documentados.

## Bloque activo: Alpha 0.9 Workout Load Entry

La rama `feature/workout-load-entry` parte exactamente de `3d23ed1`, tag `alpha-0.8.1-workout-session-recovery`. Añade calculador Decimal, preferencia kg/lb, `ExerciseLoadProfile`, `TrainingSet.load_details_json`, formulario móvil y contratos aditivos de import/export/restore/sync. Leer [`project-rules/workout-load-entry.md`](project-rules/workout-load-entry.md) y [`WORKOUT_LOAD_ENTRY.md`](WORKOUT_LOAD_ENTRY.md).

La migración nueva `20260716_0027` solo debe probarse en bases aisladas durante este bloque. No ejecutar Docker ni migraciones persistentes mientras el usuario utiliza el sistema en gimnasio. `weight_kg` conserva su semántica de total normalizado; `load_details` es opcional. Companion declara `advanced_load_details_in_planned_package=false`; no hay APK ni reloj.

Validación final del bloque: local `566 passed, 3 skipped, 1 warning`; Docker/MariaDB aislado `568 passed, 1 skipped, 1 warning`; single head y `db check` limpios. QA HTTP, migración reversible, persistencia y responsive oscuro en seis anchos pasaron sin tocar el stack activo. Solo queda pendiente un sign-off visual real de tema claro; no debe presentarse como realizado.

## Bloque activo: Alpha 0.8.1 Workout Session Recovery

La rama activa `hotfix/alpha-0.8.1-workout-session-recovery` parte de `7ee865f`, tag `alpha-0.8-companion-backend`. Para sesiones web, CSRF, drafts o idempotencia leer primero [`project-rules/workout-session-recovery.md`](project-rules/workout-session-recovery.md). El bloque añade la migración `20260715_0026`, sin cambiar los contratos Bearer, Mobile Sync o Companion.

Estado verificado: local `548 passed, 3 skipped, 1 warning`; Docker/MariaDB `550 passed, 1 skipped, 1 warning`; single head `20260715_0026` y `db check` limpio. QA responsive real pasó en tema oscuro en seis anchos; tema claro continúa pendiente por falta de emulación disponible y no debe marcarse como realizado.

P1 de captura avanzada de cargas está implementada en `feature/workout-load-entry` y en validación final aislada. No confundir `client_submission_id` web con `client_event_id` móvil.

## Bloque activo: Fase 7C

La rama `feature/phase-7c-companion-delivery` parte de `b0b6bb2`, tag exacto `alpha-0.7-mobile-sync`. Implementa Alpha 0.8: perfil/negociación companion, package 1.0, delivery persistente, checkpoints y completion sobre `TrainingSession`/Mobile Sync. Leer [`project-rules/companion-protocol.md`](project-rules/companion-protocol.md) y [`COMPANION_PROTOCOL_1_0.md`](COMPANION_PROTOCOL_1_0.md).

Estado verificado de la rama: Alembic single head `20260714_0025`; local `535 passed, 2 skipped, 1 warning`; Docker/MariaDB `536 passed, 1 skipped, 1 warning`; `db check`, QA HTTP y dry-runs operativos limpios. El sign-off visual oscuro pasó a 360/390/430/768/1024/1366 px; el tema claro sigue pendiente de una comprobación visual real.

Alpha 0.7 está integrada y publicada en `b0b6bb2`, tag `alpha-0.7-mobile-sync`, migración head `20260714_0023`. Suites local/Docker y concurrencia MariaDB pasaron. Planned workouts cuenta con cobertura Flask/HTML; el sign-off visual humano final quedó pendiente operativo.

Limitaciones vigentes: rate limiter por proceso; tombstones y cursores obsoletos report-only; sin CRDT ni last-write-wins general; sin sync write para activity/route/body/wellness/labs; sin APK/reloj/Bluetooth/telemetría continua/FIT output/vendors. `API_TOKEN_SIGNING_KEY` independiente es recomendada en homelab y obligatoria antes de exposición pública. Persiste la incompatibilidad histórica SQLite de migración `0015`.

Para tareas de sync móvil, leer también [`project-rules/mobile-sync.md`](project-rules/mobile-sync.md), [`SYNC_PROTOCOL_1_0.md`](SYNC_PROTOCOL_1_0.md) y [`SYNC_CONFLICTS.md`](SYNC_CONFLICTS.md). No confundir esta base backend con una APK implementada. Los únicos targets de push de dominio 1.0 son `planned_workout` y `completed_workout`; perfil/delivery companion son metadata del protocolo.

## API v1

Para companion leer `project-rules/api-v1.md` y `project-rules/companion-protocol.md`. Fase 7A añade Bearer persistido independiente de web y Fase 7B aporta Mobile Sync 1.0.

Este documento es el punto de entrada para Codex y otros agentes que retomen el proyecto sin depender de conversaciones anteriores.

No reemplaza a las reglas canónicas ni a los schemas. Su función es ordenar qué leer, qué manda en caso de conflicto y cuál es el estado técnico verificado al actualizar este contexto.

Última actualización documental: 2026-07-13.

Estado más reciente: `feature/phase-web-ui-homelab` parte de `e998979`, tag exacto `alpha-0.6-api-auth`. El bloque Alpha 0.6.1 consolida el shell Flask/Jinja, navegación responsive, dashboard diario, estado owner-only del homelab y gestión owner-only de dispositivos, sin migración ni cambio de contrato de datos. Para tareas web leer `docs/project-rules/web-ui.md`.

Estado histórico de Alpha 0.5: `feature/phase-6b-full-backup-recovery` partió de `f36ae9d`, tag exacto `alpha-0.4-exporters-complete`, e implementó backup/restore ZIP 1.0 sin migración nueva. Leer también `docs/project-rules/full-backup.md`, `docs/FULL_BACKUP.md` y `docs/BACKUP_SECURITY.md` para tareas de portabilidad binaria.

## Orden obligatorio de lectura

Antes de modificar el repositorio, leer en este orden:

1. `AGENTS.md`.
2. `docs/AI_WORK_CONTEXT.md`.
3. `docs/PROJECT_CONTEXT.md`.
4. `docs/project-rules/canonical-data-contract-import-update.md`.
5. `docs/project-rules/phase-5b-universal-json-import-assistant.md`.
6. `docs/project-rules/standard-json-generator-development.md` si la tarea toca Fase 5B, detección, aliases, `StandardJsonGenerator`, `UniversalJsonImportAssistant` o `AssistedImportService`.
7. `docs/project-rules/confirmed-standard-import.md` si la tarea toca confirmación o escritura real desde JSON estándar.
8. `docs/project-rules/import-audit-persistence.md` si la tarea toca auditoría persistente de importaciones.
9. `docs/project-rules/account-restore.md` si la tarea toca restore completo de cuenta.
10. `docs/ACCOUNT_RESTORE.md` y `docs/DATA_PORTABILITY.md` si la tarea toca portabilidad o round-trip.
11. `docs/project-rules/exporters.md` si la tarea toca exports o artefactos generated.
12. `docs/project-rules/web-ui.md` si la tarea toca Jinja, CSS, navegación, dashboard o flujos web.
13. `docs/ACTIVE_HANDOFF.md`, solo como handoff temporal del bloque activo.
14. README, código, tests y `git status`.

Para Fase 7C insertar `docs/project-rules/companion-protocol.md` después de las reglas API/mobile sync.

## Precedencia

Si hay conflicto:

1. JSON Schemas versionados en `schemas/` para contratos publicos de import/export.
2. Tests existentes que codifiquen el contrato esperado.
3. Reglas canonicas en `docs/project-rules/`.
4. `AGENTS.md`.
5. `docs/AI_WORK_CONTEXT.md`.
6. `docs/PROJECT_CONTEXT.md`.
7. `docs/ACTIVE_HANDOFF.md`.
8. Codigo actual para detalles de implementacion que no contradigan lo anterior.
9. README.
10. Comentarios antiguos.

`docs/ACTIVE_HANDOFF.md` es temporal. Puede orientar el siguiente bloque, pero no puede contradecir schemas, tests ni reglas canonicas.

## Estado técnico actual verificado

La rama activa `feature/phase-6-exporters-complete` parte de `2d617ed` (tag `alpha-0.3-real-file-ingestion`). Agrega Alpha 0.4: registry de exportadores, `ExportRecord`, storage generated con SHA256, Activity/Route GPX/TCX/CSV, entrenamiento HTML/PDF/ZWO/ERG/MRC y UI `/exports`. FIT de salida permanece experimental/unsupported por ausencia de encoder mantenido configurado.

La línea base limpia previa a este bloque fue `429 passed`. El cierre verificado de la rama reportó `441 passed` local y `440 passed, 1 skipped` en Docker; el skip es `test_active_handoff.py` porque la imagen no copia `docs/`.

Esta actualizacion documental se integro en `master` mediante el merge `9a5d474`.

`0356d33` queda solo como commit historico inspeccionado antes de la actualizacion.
Cada bloque posterior debe registrar su base efectiva con `git rev-parse --short master`.

Línea base verificada durante esta actualización:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

Resultado real histórico:

```text
250 passed
```

Nota: el comando anterior se ejecutó como `& '..\.venv\Scripts\python.exe' -m pytest -q` desde `backend/`.

El último merge conocido en `master` es:

```text
0356d33 Merge branch 'feature/standard-json-generator-medical-lab'
```

## Módulos principales existentes

El proyecto actual incluye, según código, tests y README:

- Auth, login/logout y administración básica.
- Uploads con SHA256, estado de importación, tipo detectado y aislamiento por usuario.
- Base de real-file imports en rama `feature/phase-5-real-importers`: GPX/TCX/CSV/FIT hacia JSON estándar, actividades/rutas persistidas, preview/confirmación/auditoría y export/restore; FIT binario vendor-neutral usa `fitdecode==0.10.0`.
- Dashboard web diario y QA operativo.
- Export completo de usuario e import-preview dry-run.
- Entrenamiento:
  - rutinas versionables;
  - sesiones completadas;
  - comparación plan vs realidad;
  - progreso y sobrecarga básica;
  - identidades y aliases de ejercicios.
- Wellness:
  - nutrición diaria;
  - gasto energético diario;
  - balance diario;
  - productos de alimento/alacena mínima;
  - recetas y bundles de recetas.
- Peso y composición corporal.
- Laboratorios médicos:
  - schema;
  - importación;
  - captura mínima;
  - reportes;
  - marcadores;
  - historial;
  - export JSON/CSV.
- Importación asistida universal, actualmente read-only en la fase de preview/generación.

No tratar APK, app de reloj, APIs privadas Magene/OnelapFit, OCR, FHIR, API REST pública, restore de binarios/ZIP o PDF/Excel avanzado como implementados si el código no lo confirma. FIT/GPX/TCX se soportan solo como importación de archivos exportados, no como sincronización con dispositivos.

La verificación local posterior al cierre de Fase 5B e importación confirmada reportó inicialmente:

```text
304 passed
```

La rama `feature/overnight-backend-qa-closure` agrega QA automatizado de mayor profundidad para `daily_energy`, `training_plan`, `completed_workout` y `medical_lab`, más fixtures ficticias en `examples/qa/standard-import/`.

## Estado real de Fase 5B

La Fase 5B existe como infraestructura read-only cerrada para los targets listados abajo:

- `SchemaDetector` detecta schemas internos oficiales de forma estricta.
- `UniversalJsonImportAssistant` analiza JSON no estándar y sugiere dominios/mappings.
- `StandardJsonGenerator` genera documentos estándar internos para algunos dominios y los valida contra schema.
- `AssistedImportService` orquesta detección, asistencia y generación en modo preview.

Estos servicios no deben escribir en DB, no deben guardar archivos y no deben ejecutar importación real.

### Targets y schemas verificados

`SUPPORTED_TARGETS` del módulo `standard_json_generator.py` actual:

| `target_type` | `schema_name` generado |
| --- | --- |
| `weigh_in_batch` | `weigh_in` |
| `food_products` | `food_product` |
| `daily_energy` | `daily_energy` |
| `daily_nutrition` | `daily_nutrition` |
| `completed_workout` | `completed_workout` |
| `medical_lab` | `medical_lab` |
| `training_plan` | `training_plan` |
| `recipe` | `recipe` |
| `recipe_bundle` | `recipe_bundle` |

La Fase 5B queda cerrada para esos targets: detección, mapping asistido, generación estándar read-only y validación contra schema.

La importación confirmada posterior a Fase 5B existe mediante `StandardImportExecutor`:

- preview y generación siguen siendo read-only;
- el commit exige confirmación explícita;
- la confirmación web se firma contra usuario, target, payload y plan;
- los tokens vencidos, reutilizados o de otro usuario se rechazan;
- el `user_id` efectivo viene del usuario autenticado/argumento del servidor;
- el plan usa operaciones `insert`, `update`, `skip`, `conflict`, `invalid`;
- el lote se ejecuta de forma atómica en la sesión de DB y debe hacer rollback ante errores de escritura;
- la ruta web mínima es `GET/POST /imports/standard`.
- la auditoría persistente de intentos confirmados existe mediante `ImportRun`.
- rutas de consulta: `GET /imports/history` y `GET /imports/history/<id>`.
- no se auditan previews ni tokens inválidos.
- no se guardan payloads crudos, tokens, trazas ni datos de salud en `ImportRun`.
- el restore completo de cuenta existe para `user_data_export` mediante `/account/restore`, con preview, token firmado, remapeo de IDs internos, commit atómico y auditoría `target_type=user_data_restore`.
- el restore completo no restaura binarios de `uploads`, no escribe `/data`, no permite elegir `user_id` y no implementa borrado ni ZIP.
- La validación local del bloque `feature/backend-complete-roundtrip` reportó `399 passed`.

Cobertura automatizada adicional agregada en la rama `feature/overnight-backend-qa-closure`:

- `daily_energy`: preview autodetectado, alias `distancia_km`, insert, skip, update parcial, batch inválido y `user_id` ajeno.
- `training_plan`: preview con paths padre, versionado insert/skip/update, SHA de versión, orden inválido y aislamiento.
- `completed_workout`: ownership de plan/version, referencias ajenas, mismatch plan/version, campos ampliados, conflict explícito y rollback tras flush.
- `medical_lab`: preview autodetectado, insert/skip/update, reemplazo de markers, valores numéricos/texto, inválidos y aislamiento.

`SchemaDetector.DEFAULT_SCHEMA_CANDIDATES` actual:

- `weigh_in`
- `daily_nutrition`
- `daily_energy`
- `food_product`
- `recipe_bundle`
- `recipe`
- `medical_lab`
- `training_plan`
- `completed_workout`
- `user_data_export`

## Invariantes del proyecto

- Todo dato de usuario debe estar asociado a `user_id`.
- Toda consulta sensible debe filtrar por `user_id`.
- Admin puede tener rutas especiales, pero no se debe mezclar información personal entre usuarios.
- Los schemas son el contrato público de JSON.
- Los aliases externos solo viven en detección, normalización o importación asistida.
- El JSON estándar generado debe usar nombres canónicos.
- Ningún generador debe inventar campos requeridos.
- Si faltan requeridos, el documento se genera con lo disponible y la validación debe marcarlo inválido.
- Preview y generación read-only no escriben en DB ni guardan archivos.
- Importación real debe pasar por importadores oficiales.
- Docker Compose y MariaDB deben conservarse compatibles.

## Reglas de seguridad y datos

- No leer, mostrar, copiar ni resumir `.env`.
- No tocar `/data`.
- No subir datos reales a Git.
- No usar datos personales, médicos, corporales, alimentarios o de entrenamiento reales en tests, fixtures o docs.
- No incluir secretos, tokens, hashes de contraseña ni rutas internas sensibles en exports o documentación.
- Usar fixtures ficticias y claramente marcadas como QA/demo.
- No usar placeholders como `Unknown`, `N/A`, `dummy`, `fallback`, `1` o `0` para satisfacer schemas.
- No ejecutar comandos destructivos como `git reset --hard`, `git clean` o `docker compose down -v` salvo instrucción explícita del usuario.

## Reglas de ramas y worktrees

- Trabajar exclusivamente en la rama indicada por el usuario.
- Revisar `git status --short --branch` antes de modificar.
- Si se usa `git worktree` para trabajo paralelo, cada agente debe tocar un dominio acotado.
- Un agente no debe modificar módulos de otros dominios salvo necesidad demostrada y explicada.
- Los cambios al dispatch central de detectores/generadores deben ser mínimos, explícitos y fáciles de revisar.
- No hacer commit ni push salvo que el usuario lo solicite explícitamente.

## Comandos de validación

Para cambios de documentación solamente:

```powershell
git diff --check
git status --short --branch
git diff --stat
git diff --name-only
```

Para cambios de backend:

```powershell
cd backend
python -m compileall -q .
python -m pytest -q
flask db check
cd ..
docker compose config --quiet
```

Si Docker está disponible y la tarea lo requiere:

```powershell
docker compose up --build -d
docker compose exec -T web flask db check
docker compose exec -T web python -m pytest -q
```

## Protocolo de entrega y handoff

Al cerrar un bloque:

1. Reportar archivos creados y actualizados.
2. Reportar si hubo migraciones; si no hubo, decirlo.
3. Reportar comandos ejecutados y resultados.
4. Confirmar que no se tocó `/data`, `.env` ni datos reales.
5. Actualizar `docs/ACTIVE_HANDOFF.md` si el siguiente agente necesita contexto temporal.
6. Mantener referencias a reglas canónicas en vez de copiar documentos completos.
7. Dejar claro qué falta y cuál es la siguiente acción concreta.

## Referencias

- Reglas de agentes: `../AGENTS.md`.
- Contexto de producto: `PROJECT_CONTEXT.md`.
- Contrato canónico: `project-rules/canonical-data-contract-import-update.md`.
- Fase 5B: `project-rules/phase-5b-universal-json-import-assistant.md`.
- Reglas de `StandardJsonGenerator`: `project-rules/standard-json-generator-development.md`.
- Importación estándar confirmada: `project-rules/confirmed-standard-import.md`.
- Real-file imports: `project-rules/real-file-imports.md`.
- Exportadores: `project-rules/exporters.md`.
- Auditoría persistente de imports: `project-rules/import-audit-persistence.md`.
- Account restore: `project-rules/account-restore.md`.
- Backup integral: `project-rules/full-backup.md`.
- Formato y seguridad de backup: `BACKUP_FORMAT_1_0.md`, `FULL_BACKUP.md`, `BACKUP_SECURITY.md` y `BACKUP_RESTORE_RUNBOOK.md`.
- Guía de restore: `ACCOUNT_RESTORE.md`.
- Portabilidad de datos: `DATA_PORTABILITY.md`.
- Handoff temporal: `ACTIVE_HANDOFF.md`.
