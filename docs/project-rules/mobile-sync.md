# Regla canónica: mobile sync

Aplica a planned workouts, completed workouts y `/api/v1/sync/*`.

1. El `user_id` efectivo siempre proviene del Bearer token.
2. La API solo expone UUID públicos persistidos.
3. Bootstrap y pull no crean datos de dominio.
4. Toda mutación exige idempotencia y validación allowlist.
5. Una entidad mutable usa revisión optimista; nunca last-write-wins silencioso.
6. Delete genera tombstone hasta que una retención segura permita borrado físico.
7. Los cursores son opacos, firmados y ligados a usuario/dispositivo.
8. Logs e idempotencia no guardan payload clínico completo, tokens ni notas.
9. Los batch informan resultado por elemento; no hay falso éxito parcial.
10. La versión de rutina de un planned/completed workout es histórica e inmutable.

Cambiar estos contratos requiere schemas, migración si aplica, pruebas SQLite y MariaDB, aislamiento con dos usuarios y actualización del protocolo.
