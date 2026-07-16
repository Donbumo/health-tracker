# Mobile Sync Foundation

Alpha 1.0 Web Daily Driver no cambia Bearer API, cursores, idempotencia ni entidades sincronizables. Las preferencias web y el Import Hub no amplían Mobile Sync y no existe APK en este bloque.

Alpha 0.8.1 añade `client_submission_id` únicamente al flujo web y a la portabilidad de `completed_workout`. No sustituye ni colisiona con `client_event_id`, no añade cookie fallback a `/api/v1` y no cambia el contrato Bearer o la idempotencia móvil.

Alpha 0.7 está integrada/publicada en `b0b6bb2`, tag `alpha-0.7-mobile-sync`, con head `20260714_0023`. Incluye planned workouts, completed upload, bootstrap/pull/push/status, revisiones, tombstones, cursor por dispositivo, cleanup CLI y UI homelab mínima. Suites local/Docker y concurrencia MariaDB pasaron; el recorrido visual humano final quedó pendiente operativo.

Alpha 0.8 amplía el mismo cursor con `companion_profile` y `companion_delivery`; no crea un segundo sistema de sync. Completion sigue produciendo el `completed_workout` existente.

Alpha 0.7 introduce la base backend para un companion futuro. No incluye APK ni aplicación de reloj.

## Alcance 1.0

- Lectura de la rutina activa mediante snapshot.
- Entrenamientos planificados ligados a una versión concreta.
- Sesiones completadas con ejercicios, series, RIR, RPE y descanso.
- Bootstrap, pull incremental, push por lotes y estado por dispositivo.
- Identidad pública UUID, revisiones, conflictos, tombstones e idempotencia.

Las entidades editables por sync 1.0 son `planned_workout` y `completed_workout`. Actividades, rutas, peso, nutrición, energía, laboratorios, uploads y exports no admiten push en esta versión.

Todos los endpoints requieren Bearer API v1. No aceptan cookie web, token en query ni selección de `user_id`. Los cursores están firmados y ligados al usuario y dispositivo. Los logs solo incluyen eventos allowlisted e IDs públicos truncados; nunca tokens, notas o payloads clínicos completos.

Consulta [SYNC_PROTOCOL_1_0.md](SYNC_PROTOCOL_1_0.md), [SYNC_CONFLICTS.md](SYNC_CONFLICTS.md) y [SYNC_IDEMPOTENCY.md](SYNC_IDEMPOTENCY.md).

Límites: el rate limiter es por proceso, tombstones/cursores obsoletos siguen report-only, no hay CRDT ni last-write-wins general y activity/route/body/wellness/labs no tienen sync write. `API_TOKEN_SIGNING_KEY` independiente es recomendada en homelab y obligatoria antes de exposición pública. Persiste la incompatibilidad histórica de SQLite en migración `0015`.
