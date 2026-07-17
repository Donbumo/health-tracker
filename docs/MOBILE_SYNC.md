# Mobile Sync Foundation

Mobile Sync 1.0 extiende Bearer API v1 con planned workouts, completed upload, bootstrap/pull/push/status, revisiones, tombstones, cursor por dispositivo e idempotencia.

`client_submission_id` pertenece al flujo web; no sustituye ni colisiona con `client_event_id` móvil. Las preferencias web y el Import Hub tampoco amplían las entidades sincronizables.

Companion reutiliza el cursor con `companion_profile` y `companion_delivery`; no crea un segundo sistema de sync. Completion sigue produciendo el `completed_workout` existente. El backend no implica que exista APK ni aplicación de reloj.

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
