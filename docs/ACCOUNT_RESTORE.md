# Account restore

Guía operativa del restore completo de cuenta para Alpha 0.2.

Este flujo restaura un export generado por `/account/export.json` dentro de la cuenta autenticada actual. No es restore ZIP, no restaura archivos binarios y no permite seleccionar `user_id`.

## Rutas

- `GET /account/data`: centro de datos de cuenta.
- `GET /account/export.json`: export completo del usuario autenticado.
- `GET/POST /account/restore`: carga y preview de un `user_data_export`.
- `POST /account/restore/confirm`: confirmación firmada y commit transaccional.
- `GET /imports/history`: historial saneado de imports/restores.
- `GET /imports/history/<id>`: detalle saneado de un `ImportRun` propio.

## Flujo

1. El usuario inicia sesión.
2. Descarga `/account/export.json`.
3. En otra cuenta o instalación compatible, abre `/account/restore`.
4. Sube el JSON.
5. Revisa el plan `insert/update/skip/conflict/invalid/unsupported`.
6. Confirma explícitamente si el plan es válido.
7. El servicio vuelve a validar el payload y el plan.
8. El commit se ejecuta en transacción.
9. Se registra auditoría saneada con `target_type=user_data_restore`.

## Contrato de seguridad

- El `user_id` efectivo proviene de la sesión autenticada.
- El usuario, email y rol del archivo se ignoran.
- El token de confirmación está firmado contra usuario, modo, versión, schema, hash de payload y hash de plan.
- El token tiene expiración y se marca como usado en la sesión web para evitar replay accidental.
- Preview no escribe DB, no guarda archivos y no crea `ImportRun`.
- Confirmaciones inválidas, payloads modificados y planes modificados no escriben datos.
- No se guardan payloads crudos, tokens, trazas ni valores sensibles en `ImportRun`.
- El historial filtra siempre por `current_user.id`.

## Secciones restaurables

| Sección | Política |
| --- | --- |
| `food_products` | insert/update/skip por usuario + nombre + marca |
| `recipes` | insert/update/skip por usuario + nombre; ingredientes deben referenciar productos existentes o incluidos en el mismo export |
| `weigh_ins` | insert/update/skip por usuario + `recorded_at` + fuente |
| `daily_energy` | insert/update/skip por usuario + fecha |
| `daily_nutrition` | insert/update/skip por usuario + fecha |
| `medical_lab_reports` | insert/update/skip por usuario + fecha + laboratorio |
| `training_plans` | insert/update/skip por usuario + nombre y SHA de versiones |
| `training_sessions` | insert/skip; update inseguro queda como conflicto |

Secciones no restaurables:

- `uploads`: metadata sin binarios.
- `daily_balances`: datos derivados recalculables.

## Atomicidad

El restore registra `pending` antes de mutaciones de dominio. Si el plan tiene conflictos o inválidos, se registra `blocked` y no se escriben datos. Si ocurre un error durante la escritura, se hace rollback completo y se registra `failed` mediante una transacción limpia de auditoría.

`succeeded` solo debe existir cuando los datos de dominio y la finalización de auditoría quedan confirmados.

## Límites

El servicio aplica límites de tamaño, profundidad, cantidad de nodos, longitud de strings y tamaño de secciones para evitar payloads abusivos. No se deben relajar estos límites sin prueba y justificación.

## Pendiente explícito

- Restore de archivos binarios.
- Restore ZIP.
- Borrado destructivo o sincronización espejo.
- Import desde API externa.
- Selección manual de usuario destino.
