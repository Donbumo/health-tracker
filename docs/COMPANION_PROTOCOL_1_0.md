# Companion Delivery Protocol 1.0

Alpha 1.1 implementa el protocolo en un cliente Android de teléfono. Alpha 0.9 conserva `load_details` opcional cuando llega en un resultado completado válido. Los packages planeados aún no transportan perfiles/componentes avanzados y declaran `advanced_load_details_in_planned_package=false`; no debe inferirse soporte de reloj.

Protocolo vendor-neutral para preparar y ejecutar entrenamientos. El cliente Android cubre login, negociación, package, ejecución, cola offline y completion; no incluye reloj, Bluetooth ni integración de fabricante.

## Flujo

1. Login Bearer API v1.
2. `POST /api/v1/companion/negotiate` con versiones, features, métricas y límites.
3. `POST /api/v1/companion/deliveries` con `Idempotency-Key` y un `planned_workout_id` propio.
4. Descargar el snapshot desde `GET .../<delivery_id>/package`.
5. Confirmar `ack`, iniciar, enviar checkpoints pequeños y completar o abortar.
6. Reintentar con la misma clave/evento devuelve replay seguro; contenido distinto produce conflicto.

Versiones iniciales: protocol `1.0`, workout package `1.0`, result `1.0`. No hay downgrade silencioso.

Las respuestas usan UUID públicos, RFC3339 UTC, `request_id`, `Cache-Control: no-store` y errores JSON estables. La identidad efectiva siempre viene del token.

## Lecturas móviles Alpha 1.2

Companion 1.0 conserva sin cambios sus mutaciones y versiones. Alpha 1.2 añade lecturas Bearer owner-only: `/api/v1/mobile/history`, `/api/v1/mobile/history/<session_public_id>`, `/api/v1/mobile/progress/summary`, `/api/v1/mobile/progress/exercises` y `/api/v1/mobile/progress/exercises/<exercise_public_id>`. Historial usa cursor firmado y límite 1–100; progreso limita rangos a 7/30/90/180/365 días o todo. Los contratos están en `mobile_history.schema.json` y `mobile_progress.schema.json`.

Consulta [COMPANION_CAPABILITIES.md](COMPANION_CAPABILITIES.md), [COMPANION_WORKOUT_PACKAGE.md](COMPANION_WORKOUT_PACKAGE.md), [COMPANION_DELIVERY.md](COMPANION_DELIVERY.md), [COMPANION_PROGRESS.md](COMPANION_PROGRESS.md) y la [regla canónica](project-rules/companion-protocol.md).
