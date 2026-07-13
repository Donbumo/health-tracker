# API v1

Base URL: `/api/v1`. Éxito usa `data` y `meta` (`api_version`, `request_id`); error usa `error.code`, mensaje seguro, `details` y el mismo `meta`.

Endpoints: `GET /health`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/logout-all`, `GET /me`, `GET /devices`, `DELETE /devices/<uuid>`, `GET /companion/bootstrap` y `GET /routines/active`.

Los privados solo aceptan `Authorization: Bearer`; cookies, query parameters y Flask-Login no autentican la API. Fechas son RFC3339 UTC. No existen aún sync offline, conflictos, tombstones, planned workouts, watch bridge ni endpoints falsos. Fase 7B deberá definir `Idempotency-Key` antes de aceptar escrituras sincronizadas.
