# Idempotencia de sesiones web

Las nuevas sesiones web llevan `client_submission_id`, UUID estable desde que se abre el formulario. La base aplica `UNIQUE(user_id, client_submission_id)`; sesiones históricas conservan `NULL`.

Política:

- mismo usuario + mismo submission ID + mismo payload canónico: replay seguro hacia la sesión existente;
- mismo usuario + mismo submission ID + payload distinto: `submission_conflict`;
- otro submission ID para un planned workout ya completado: conflicto;
- una carrera se resuelve con constraints DB, rollback y lectura del ganador;
- no se deduplica entre usuarios.

El hash cubre el documento canónico allowlisted. `client_submission_id` se conserva en JSON de `completed_workout`, export completo, backup y restore. No sustituye a `client_event_id`: este último pertenece a Mobile Sync/Bearer y mantiene su contrato.

El commit incluye `TrainingSession`, ejercicios, series, asociación y estado del `PlannedWorkout`, `SyncChange`, metadata del archivo generado y eliminación del borrador servidor. Cualquier excepción revierte el conjunto y conserva el borrador.

