# API v1

## Companion delivery 1.0

Alpha 0.8 añade perfil/negociación, packages versionados, deliveries, ACK, checkpoints y completion en `/api/v1/companion/*`. Bearer fija usuario/dispositivo; las mutaciones usan idempotencia y revisión. Ver [COMPANION_PROTOCOL_1_0.md](COMPANION_PROTOCOL_1_0.md).

## Mobile sync 1.0

Alpha 0.7 añade endpoints Bearer owner-only para planned workouts, completed workouts y `/sync/{bootstrap,pull,push,status}`. Las mutaciones requieren `Idempotency-Key`; los UUID son públicos y persistentes. El soporte de escritura se limita a `planned_workout` y `completed_workout`.

Contrato detallado: [SYNC_PROTOCOL_1_0.md](SYNC_PROTOCOL_1_0.md).

Base URL: `/api/v1`. Éxito usa `data` y `meta` (`api_version`, `request_id`); error usa `error.code`, mensaje seguro, `details` y el mismo `meta`.

## AI Foundation

Beta 1.1 agrega `GET /ai/status`, create/list/get/delete de `/ai/conversations`, `POST /ai/conversations/<uuid>/messages` y `POST /ai/conversations/<uuid>/retry`. Todos requieren Bearer, derivan el owner del token y usan IDs públicos. Los mensajes solo pueden invocar la allowlist server-side documentada en [AI_FOUNDATION.md](AI_FOUNDATION.md); no aceptan `user_id`, SQL, shell, filesystem o URLs. Los drafts devueltos son `pending_confirmation` y esta fase no expone confirmación/escritura.

Endpoints: `GET /health`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/logout-all`, `GET /me`, `GET /devices`, `DELETE /devices/<uuid>`, `GET /companion/bootstrap` y `GET /routines/active`.

Los privados solo aceptan `Authorization: Bearer`; cookies, query parameters y Flask-Login no autentican la API. Fechas son RFC3339 UTC. Sync offline, conflictos, tombstones y planned workouts existen desde Alpha 0.7. Watch bridge, Bluetooth, telemetría continua e integraciones de fabricante siguen sin implementar.
