# Mobile Sync Foundation

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
