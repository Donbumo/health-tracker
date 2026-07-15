# Companion progress y completion

`POST .../progress` recibe checkpoints pequeños con UUID de evento y secuencia estrictamente creciente. Replay exacto es duplicado; mismo UUID con contenido distinto o gap/stale produce conflicto.

Tipos: `heartbeat`, `exercise_started`, `set_completed`, `exercise_completed`, `paused`, `resumed`, `checkpoint`. El payload solo admite campos escalares allowlisted; no acepta arrays de FC, GPS, trackpoints ni telemetría continua.

`POST .../complete` valida versión, revisión, hash, planned workout y evento. Reutiliza `create_completed_workout`, crea una sola `TrainingSession`, completa el planned workout y delivery y emite `SyncChange` dentro de la misma transacción. Un rollback no deja sesión parcial.
