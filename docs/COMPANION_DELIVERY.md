# Companion workout deliveries

Alpha 0.8.1 no cambia negociación, package, delivery ni completion Companion. El nuevo `client_submission_id` pertenece al formulario web; Companion conserva sus IDs de operación y el `client_event_id` de Mobile Sync.

Estados: `prepared`, `delivered`, `acknowledged`, `started`, `completed`, `aborted`, `failed`, `expired`, `cancelled`.

`ack` valida `package_hash`, `received_at`, `client_operation_id` y revisión. `start`, `abort` y `fail` exigen revisión e idempotencia. Estados terminales no admiten nuevas transiciones. Motivos de fallo son códigos allowlisted; no se aceptan logs arbitrarios.

La clave natural de snapshot es dispositivo + perfil + planned workout + revisión. Un reintento conserva el mismo UUID/package. Un UUID de otro usuario responde 404.

`flask companion cleanup` es dry-run. `--apply` solo expira deliveries vencidas y elimina checkpoints antiguos de deliveries terminales; no borra sesiones ni planned workouts.
