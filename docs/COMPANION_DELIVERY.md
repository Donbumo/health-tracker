# Companion workout deliveries

Alpha 1.1 añade un cliente Android de teléfono que consume este contrato, conserva packages verificados por SHA256 y reintenta operaciones mediante una cola durable. No añade app de reloj, Bluetooth ni capacidades de fabricante.

Alpha 1.0 Web Daily Driver solo reorganizó la navegación y agenda web. No cambió negociación, package, delivery, checkpoints ni completion.

Alpha 0.8.1 no cambia negociación, package, delivery ni completion Companion. El nuevo `client_submission_id` pertenece al formulario web; Companion conserva sus IDs de operación y el `client_event_id` de Mobile Sync.

Estados: `prepared`, `delivered`, `acknowledged`, `started`, `completed`, `aborted`, `failed`, `expired`, `cancelled`.

`ack` valida `package_hash`, `received_at`, `client_operation_id` y revisión. `start`, `abort` y `fail` exigen revisión e idempotencia. Estados terminales no admiten nuevas transiciones. Motivos de fallo son códigos allowlisted; no se aceptan logs arbitrarios.

La clave natural de snapshot es dispositivo + perfil + planned workout + revisión. Un reintento conserva el mismo UUID/package. Un UUID de otro usuario responde 404.

`flask companion cleanup` es dry-run. `--apply` solo expira deliveries vencidas y elimina checkpoints antiguos de deliveries terminales; no borra sesiones ni planned workouts.
