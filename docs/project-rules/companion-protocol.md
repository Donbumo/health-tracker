# Regla canónica: Companion Delivery Protocol

Aplica a `/api/v1/companion/*`, perfiles, packages, deliveries, checkpoints y completion.

1. Bearer determina usuario y dispositivo; el body nunca selecciona `user_id` ni `device_id`.
2. Todo ID externo de entidad es UUID v4 persistente; no se exponen IDs internos.
3. Negociación, package y resultado usan versiones explícitas. Una versión vacía o incompatible se rechaza; no hay downgrade silencioso.
4. El package es un snapshot allowlisted e inmutable de un `PlannedWorkout` y su `TrainingPlanVersion` histórica. Campos descartados se informan.
5. La entrega usa revisión optimista, transiciones allowlisted e idempotencia. Estados terminales no aceptan nuevas mutaciones.
6. Checkpoints son pequeños, secuenciales e idempotentes. No aceptan series de FC, GPS ni telemetría continua.
7. Completion valida package hash y reutiliza el importador/servicio de completed workout dentro de una transacción; no duplica `TrainingSession`.
8. Perfil, delivery, progress y completion son owner-only; UUID ajeno responde 404 y un dispositivo revocado no opera.
9. Logs contienen eventos allowlisted e IDs abreviados, nunca tokens, Authorization, notas o payloads completos.
10. Sync existente se amplía; no se crea segundo cursor ni infraestructura de auditoría paralela.
11. Cambios requieren schemas, migración aditiva/reversible, pruebas SQLite/MariaDB, concurrencia, aislamiento y documentación de capacidades honestas.
12. `watch_bridge`, Bluetooth, telemetría continua, FIT output e integraciones de fabricante permanecen `false` hasta existir implementación probada.
