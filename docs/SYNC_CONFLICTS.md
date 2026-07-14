# Conflictos de sincronización

Health Tracker no usa last-write-wins ni CRDT en Sync 1.0.

- Una mutación existente requiere `base_revision`.
- Si coincide, la operación se aplica y la revisión aumenta.
- Si es antigua, se devuelve `revision_conflict` con revisión/fecha del servidor y opciones `refresh` o `retry_with_current_revision`.
- Un UUID ajeno se comporta como no encontrado y no revela existencia.
- El mismo `client_event_id` con otro hash produce `event_conflict`.
- Un delete permitido genera tombstone. Un planned workout ya completado no se puede borrar.

Los clientes deben refrescar, mostrar el conflicto al usuario y reenviar una decisión explícita. No deben incrementar revisiones localmente a ciegas.
