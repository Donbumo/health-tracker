# Sync Protocol 1.0

Alpha 0.9 permite `load_details` 1.0 opcional dentro de cada set de `completed_workout`. Es aditivo: `weight_kg` continúa obligatorio para clientes 1.0 anteriores, mientras el servidor verifica que coincida con modo, unidad y componentes.

## Flujo

1. Login API y registro del dispositivo.
2. `GET /api/v1/sync/bootstrap` para el snapshot inicial y cursor firmado.
3. Trabajo offline.
4. `POST /api/v1/sync/push` con `Idempotency-Key` y operaciones identificadas.
5. `GET /api/v1/sync/pull?cursor=...` hasta `has_more=false`.
6. `GET /api/v1/sync/status` para diagnóstico local.

El pull ordena por secuencia ascendente. El cursor pertenece a un único usuario/dispositivo; no es un ID de base de datos. Los filtros avanzan por los cambios escaneados, por lo que no se atascan ante entidades no seleccionadas.

Push acepta como máximo el límite publicado por bootstrap. Cada operación devuelve `accepted`, `duplicate`, `conflict`, `invalid`, `forbidden` o `unsupported`. Los resultados parciales son explícitos. Un fallo de base de datos no se convierte en éxito parcial silencioso.

Las respuestas de bootstrap publican versiones de schema y límites. El rate limiter sigue siendo por proceso; un despliegue público multi-worker requiere un backend compartido.
