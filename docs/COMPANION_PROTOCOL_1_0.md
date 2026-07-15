# Companion Delivery Protocol 1.0

Protocolo backend vendor-neutral para preparar y ejecutar entrenamientos en un companion futuro. No incluye APK, reloj, Bluetooth ni integración de fabricante.

## Flujo

1. Login Bearer API v1.
2. `POST /api/v1/companion/negotiate` con versiones, features, métricas y límites.
3. `POST /api/v1/companion/deliveries` con `Idempotency-Key` y un `planned_workout_id` propio.
4. Descargar el snapshot desde `GET .../<delivery_id>/package`.
5. Confirmar `ack`, iniciar, enviar checkpoints pequeños y completar o abortar.
6. Reintentar con la misma clave/evento devuelve replay seguro; contenido distinto produce conflicto.

Versiones iniciales: protocol `1.0`, workout package `1.0`, result `1.0`. No hay downgrade silencioso.

Las respuestas usan UUID públicos, RFC3339 UTC, `request_id`, `Cache-Control: no-store` y errores JSON estables. La identidad efectiva siempre viene del token.

Consulta [COMPANION_CAPABILITIES.md](COMPANION_CAPABILITIES.md), [COMPANION_WORKOUT_PACKAGE.md](COMPANION_WORKOUT_PACKAGE.md), [COMPANION_DELIVERY.md](COMPANION_DELIVERY.md), [COMPANION_PROGRESS.md](COMPANION_PROGRESS.md) y la [regla canónica](project-rules/companion-protocol.md).
