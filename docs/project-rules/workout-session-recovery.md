# Regla: recuperación de sesiones web

Para cambios en captura web de sesiones:

- mantener CSRF activo y guardar solo por POST;
- preservar todos los campos mediante borrador local y servidor, sin introducirlos en cookie de sesión;
- nunca almacenar tokens, cookies, Authorization, secretos o payload clínico en logs;
- usar únicamente IDs públicos en navegador y endpoints;
- mantener estable `client_submission_id` durante reload, CSRF, red y reintentos;
- no eliminar ningún borrador antes de confirmar la sesión;
- aplicar `UNIQUE(user_id, client_submission_id)` y comparar el hash canónico en replays;
- confirmar sesión, relaciones, planned workout, sync y eliminación del borrador en una sola transacción;
- mantener separados `client_submission_id` web y `client_event_id` móvil;
- comprobar owner-only, cross-user 404, CSRF, tamaño, expiración, carrera y rollback;
- conservar export, backup y restore del identificador.

Leer también [WORKOUT_SESSION_RECOVERY.md](../WORKOUT_SESSION_RECOVERY.md), [WORKOUT_DRAFTS.md](../WORKOUT_DRAFTS.md) y [WORKOUT_SUBMISSION_IDEMPOTENCY.md](../WORKOUT_SUBMISSION_IDEMPOTENCY.md).

