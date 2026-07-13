# Companion bootstrap

`GET /api/v1/companion/bootstrap` entrega hora, IDs públicos, timezone, capabilities y resumen de rutina. Son true `backup_zip`, `raw_file_import`, `advanced_exports`; son false `offline_sync_push`, `incremental_pull`, `planned_workouts`, `watch_bridge`, `fit_output`.

El modelo tiene versión activa por rutina, no rutina global activa. API v1 elige determinísticamente la rutina propia actualizada más recientemente y declara `selection_policy = "most_recent_plan_active_version"`; no representa una preferencia persistida del usuario. Fase 7B debería añadir selección explícita si la requiere.

`GET /api/v1/routines/active` es read-only y lleva ETag SHA-256. Contratos: `schemas/companion_bootstrap.schema.json` y `schemas/active_routine_api.schema.json`.
