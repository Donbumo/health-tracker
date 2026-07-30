# Mobile Sync Foundation

Mobile Sync 1.0 extiende Bearer API v1 con planned workouts, completed upload, bootstrap/pull/push/status, revisiones, tombstones, cursor por dispositivo e idempotencia.

`client_submission_id` pertenece al flujo web; no sustituye ni colisiona con `client_event_id` móvil. Las preferencias web y el Import Hub tampoco amplían las entidades sincronizables.

Companion reutiliza el cursor con `companion_profile` y `companion_delivery`; no crea un segundo sistema de sync. El cliente Android persiste cada página y su cursor en una sola transacción Room, y completion sigue produciendo el `completed_workout` existente. El schema de pull admite las cuatro clases observables; solo `planned_workout` y `completed_workout` son editables por push.

## Alcance 1.0

- Lectura de la rutina activa mediante snapshot.
- Entrenamientos planificados ligados a una versión concreta.
- Sesiones completadas con ejercicios, series, RIR, RPE y descanso.
- Bootstrap, pull incremental, push por lotes y estado por dispositivo.
- Identidad pública UUID, revisiones, conflictos, tombstones e idempotencia.

Las entidades editables por el push genérico de sync 1.0 son `planned_workout` y `completed_workout`. Actividades, rutas, peso, nutrición, energía, laboratorios, uploads y exports no se añaden a ese push genérico.

Todos los endpoints requieren Bearer API v1. No aceptan cookie web, token en query ni selección de `user_id`. Los cursores están firmados y ligados al usuario y dispositivo. Los logs solo incluyen eventos allowlisted e IDs públicos truncados; nunca tokens, notas o payloads clínicos completos.

Consulta [SYNC_PROTOCOL_1_0.md](SYNC_PROTOCOL_1_0.md), [SYNC_CONFLICTS.md](SYNC_CONFLICTS.md) y [SYNC_IDEMPOTENCY.md](SYNC_IDEMPOTENCY.md).

Límites: el rate limiter es por proceso, tombstones/cursores obsoletos siguen report-only, no hay CRDT ni last-write-wins general y activity/route/body/wellness/labs no tienen sync write. `API_TOKEN_SIGNING_KEY` independiente es recomendada en homelab y obligatoria antes de exposición pública. Persiste la incompatibilidad histórica de SQLite en migración `0015`.

Alpha 1.2 no añade una entidad editable ni otro cursor a Mobile Sync. Un cambio `completed_workout` actualiza la sesión estructurada de Room y marca historial/progreso para refresh mediante la misma ejecución coalescida. La lectura paginada de historial tiene su propio cursor firmado de consulta, no sustituye ni avanza el cursor incremental del dispositivo.

Alpha 1.3 añade `training_plan` al pull compartido. Las mutaciones de rutina usan endpoints agregados Bearer + `Idempotency-Key` porque deben publicar `TrainingPlanVersion`; no se introducen operaciones genéricas de push ni last-write-wins. Programar continúa creando `planned_workout`, y Companion entrega su snapshot por el protocolo 1.0. Clientes anteriores ignoran la nueva entidad/capacidades y los campos prescritos aditivos.

Alpha 1.4 mantiene el cursor compartido intacto y usa endpoints agregados Bearer para cuerpo, nutrición, catálogo y pasos. Cada operación durable lleva UUID, idempotency key, revisión y payload mínimo; el worker la procesa antes de refrescar salud/progreso. La negociación anuncia `mobile_health_logging`, `mobile_body_stats`, `mobile_nutrition`, `mobile_food_catalog` y `mobile_steps`. Los clientes anteriores ignoran estas capacidades aditivas.

Alpha 1.5 tampoco añade entidades al push genérico ni otro cursor Mobile Sync. Health Connect escribe primero en Room y reutiliza esos endpoints agregados con `source=health_connect` para cuerpo/nutrición y `source=health_connect_aggregate` para pasos. El contrato `mobile_health.schema.json` añade de forma opcional `client_event_id` y procedencia; el servidor deriva siempre el owner del Bearer token.

Alpha 1.6 mantiene Mobile Sync y backend intactos. Registro de fuentes, confirmaciones Health Connect, asociaciones/association IDs, MAC, GATT, manufacturer fingerprints, capturas, frames, evidencia de protocolo y posibles duplicados experimentales permanecen locales. Una futura fuente `xiaomi_s400_ble` no se enviará hasta que exista protocolo verificado y un cambio contractual aditivo, owner-only e idempotente; la infraestructura actual no publica valores BLE.

Peso manual y Health Connect pueden coexistir incluso en el mismo timestamp porque la clave natural incorpora la fuente. Cuerpo, nutrición y pasos aceptan un `client_event_id` UUID estable por usuario y devuelven el recurso existente en replays; el UUID público y la revisión siguen gobernando PATCH/DELETE. Editar un import de cuerpo o nutrición solo permite la transición `health_connect → user_override`. La migración `20260726_0032` es aditiva salvo el ajuste controlado de la restricción de peso, y añade procedencia nutricional e identidades cliente sin exponer origins o tokens Health Connect.

Los pasos se identifican por usuario, fecha y fuente. `manual` puede coexistir con imports existentes; la presentación elige manual cuando existe, sin sumar fuentes potencialmente solapadas ni sobrescribir silenciosamente el import. Los conflictos de salud no avanzan el cursor ni pierden la copia local: quedan visibles hasta una resolución explícita.

La agenda reutiliza `GET /api/v1/planned-workouts?from=<date>&to=<date>` con rango validado y acotado, `GET /api/v1/planned-workouts/<uuid>` para consultar estado/revisión, `PATCH` sobre el mismo recurso para moverlo conservando su UUID y `POST .../cancel` para cancelarlo. Todas las rutas derivan el owner del Bearer token y un recurso ajeno responde 404. Preparar de nuevo una delivery con la misma programación, dispositivo, perfil y revisión devuelve la existente; una revisión posterior publica un snapshot nuevo sin mutar packages ni drafts anteriores.
