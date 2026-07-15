# Companion bootstrap

Alpha 0.8 agrega al bootstrap el perfil companion negociado, versiones `1.0`, deliveries activas y capabilities honestas. La ausencia de perfil se expresa como `null`; el bootstrap no negocia ni crea deliveries.

## Bootstrap de sincronización

`GET /api/v1/sync/bootstrap` complementa el bootstrap companion original con cursor firmado, ventana de planned workouts, sesiones recientes, límites y versiones de schema. `active_routine.selection_policy` continúa siendo `most_recent_plan_active_version`; no representa una preferencia persistida.

`GET /api/v1/companion/bootstrap` entrega hora, IDs públicos, timezone, capabilities, resumen de rutina y estado companion. Son true `offline_sync_push`, `incremental_pull`, `planned_workouts`, `companion_delivery`, `capability_negotiation`, `progress_checkpoints` y `workout_package`; son false `watch_bridge`, `bluetooth_bridge`, `continuous_telemetry`, `fit_output` y vendors.

El modelo tiene versión activa por rutina, no rutina global activa. API v1 elige determinísticamente la rutina propia actualizada más recientemente y declara `selection_policy = "most_recent_plan_active_version"`; no representa una preferencia persistida del usuario. Fase 7B debería añadir selección explícita si la requiere.

`GET /api/v1/routines/active` es read-only y lleva ETag SHA-256. Contratos: `schemas/companion_bootstrap.schema.json` y `schemas/active_routine_api.schema.json`.
