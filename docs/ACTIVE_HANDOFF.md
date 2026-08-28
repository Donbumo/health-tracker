# Handoff activo

## Estado actual

- Rama `feature/external-integrations-strava`; la vertical slice de External Integrations está implementada con Strava como primer provider read-only.
- `IntegrationProvider` y el registry allowlisted separan OAuth, refresh, revocación, pull/fetch y normalización del dominio core.
- `ExternalAccount`, `ExternalSyncCursor`, `ExternalResource` y `ExternalImportEvent` son owner-only; la migración única `20260827_0039` está sobre `20260811_0038`.
- Access/refresh tokens usan AES-GCM con clave de entorno independiente y nunca entran en templates, read models, exports ni portabilidad.
- El sync inicial está acotado, el incremental conserva overlap/checkpoint, el upsert es idempotente y la procedencia `external_provider/strava` llega a vistas, exports y read models AI existentes.
- El webhook público solo valida y encola; `flask integrations process-pending-events` procesa create/update/delete/deauthorization sin añadir Redis/Celery.

## Trabajo en curso

- No queda implementación funcional pendiente en la rama.
- Falta el smoke OAuth real porque el entorno local no tiene `STRAVA_CLIENT_ID` ni `STRAVA_CLIENT_SECRET` configurados; el sistema está ready for real OAuth smoke.

## Pruebas relevantes

- Suite focal de integraciones sin red: 19 passed, 1 skipped; incluye contrato HTTP Strava mockeado, OAuth/state/scopes, AES-GCM, refresh rotation, sync, dedup, errores, webhooks, UI/AI, portabilidad y cascadas.
- MariaDB 11.4 local: `flask db upgrade`, `db current` en `20260827_0039 (head)` y `db check` sin cambios pendientes.
- Gate MariaDB de refresh concurrente con token rotado: 1 passed en schema QA temporal separado y ya eliminado.
- Suite backend completa: 849 passed, 14 skipped; `compileall` correcto. El warning único corresponde al fixture deliberado de ZIP duplicado en Full Backup.

## Bloqueadores y riesgos

- No hay bloqueadores funcionales conocidos.
- El smoke real requiere registrar la app en Strava y configurar las credenciales/verify token/clave de cifrado sin imprimirlos ni versionarlos.
- No se hizo merge, tag ni cambio en NAS.

## Siguiente paso

- QA real local: connect, identity, backfill inicial, repeat sync sin duplicados, visibilidad UI/AI y disconnect/reconnect seguro.
- Tras aprobar ese smoke, revisar operativamente callback público y suscripción webhook antes de cualquier despliegue al NAS.
