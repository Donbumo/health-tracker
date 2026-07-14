# Idempotencia de sync

Toda mutación móvil requiere `Idempotency-Key`. La clave se guarda únicamente como SHA256 y se limita por usuario y dispositivo.

- misma clave + mismo request: replay de la respuesta allowlisted;
- misma clave + request distinto: HTTP 409;
- mismo `client_operation_id`: una sola aplicación, aunque cambie el batch;
- mismo `client_event_id` y contenido: misma sesión;
- mismo event ID con contenido distinto: conflicto.

La reclamación usa constraint único de base de datos y savepoint. MariaDB serializa las reclamaciones concurrentes. Las respuestas persistidas contienen solo IDs públicos, estado y revisión: no notas, sets, snapshots ni token.

MariaDB usa aislamiento `READ COMMITTED` para que el perdedor de una carrera de constraint único pueda observar y reproducir el resultado ya confirmado, sin convertirlo en un conflicto falso.

`flask mobile-sync cleanup` informa sin borrar; `--apply` elimina idempotencia vencida y cambios antiguos solo si ningún cursor activo los necesita. Los tombstones y cursores obsoletos son report-only en esta fase.
