# Regla canónica: auditoría persistente de importación estándar

Esta regla aplica a la auditoría de importaciones estándar confirmadas posteriores a Fase 5B.

## Objetivo

La auditoría debe permitir responder qué ocurrió en un intento confirmado de importación sin duplicar datos de salud, nutrición, entrenamiento, laboratorio o archivos crudos.

## Entidad actual

El modelo persistente es `ImportRun`.

Cada `ImportRun` representa un intento confirmado de importación estándar, incluyendo intentos que terminan en:

- `succeeded`
- `blocked`
- `failed`

Preview, detección, mapping y generación estándar read-only no crean `ImportRun`.

## Qué se guarda

Se permite guardar:

- `user_id`
- `target_type`
- `source_type`
- `status`
- `started_at`
- `completed_at`
- conteos agregados:
  - total
  - insert
  - update
  - skip
  - conflict
  - invalid
- `payload_sha256`
- `plan_sha256`
- `error_code`
- `error_message` sanitizado y truncado
- `metadata_json` con allowlist de datos no sensibles

Metadata permitida:

- `schema_version`
- `requested_type`
- `detected_type`
- `source_path`
- `document_count`
- `route`
- `mode`
- `contract_version`
- `operation_names`

## Qué no se guarda

No guardar:

- payload original completo;
- JSON estándar generado completo;
- datos clínicos, alimentos, macros, notas médicas o notas privadas;
- tokens firmados;
- cookies;
- trazas/stack traces;
- secretos;
- rutas internas sensibles;
- contenido crudo de uploads.

## Ciclo de vida

- Confirmación válida y commit exitoso: `succeeded`.
- Confirmación válida con plan bloqueado por `invalid` o `conflict`: `blocked`.
- Error durante escritura: rollback de datos de dominio y luego `failed` persistido.
- Token inválido, expirado, manipulado o de otro usuario: no se crea `ImportRun`.
- Repetición exacta: crea un nuevo `ImportRun` con operaciones `skip`; no se deduplican runs.

## Transacciones

La auditoría no debe romper la atomicidad del lote:

- Los datos de dominio se confirman solo si todo el lote aplicable termina correctamente.
- Si falla la escritura después de `flush`, se hace rollback completo de dominio.
- El `ImportRun failed` se registra después del rollback para no perder la auditoría.

## Aislamiento

Toda consulta de `ImportRun` debe filtrar por `user_id`.

Un usuario normal solo puede ver sus propios runs.

No agregar impersonación ni selector libre de `user_id`.

## Retención

La política inicial conserva runs agregados indefinidamente porque no contienen payload crudo. Un comando de pruning puede agregarse en una fase futura si se define una política operativa explícita; debe borrar solo `ImportRun` antiguos y nunca datos de dominio.

