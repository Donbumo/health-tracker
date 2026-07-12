# Regla canónica: account restore

Esta regla aplica al restore completo de `user_data_export`.

No reemplaza la regla de importación estándar confirmada. `/imports/standard` opera por dominio; `/account/restore` opera sobre un export completo de cuenta.

## Separación de fases

El flujo debe mantenerse separado:

1. Carga JSON.
2. Validación de límites.
3. Validación contra `user_data_export.schema.json`.
4. Preview read-only.
5. Plan de restore.
6. Token de confirmación.
7. Confirmación explícita.
8. Validación repetida.
9. Commit transaccional.
10. Auditoría saneada.

Preview nunca debe escribir DB ni crear archivos.

## Identidad y aislamiento

- El usuario destino siempre es el usuario autenticado o el `user_id` del servidor.
- El `user.id`, `user.email`, `user.role` y cualquier `user_id` del archivo no pueden cambiar el destino.
- No debe existir selector libre de usuario destino.
- Las consultas de historial y detalle deben filtrar por `current_user.id`.
- Un usuario no debe poder inferir runs ajenos por `/imports/history/<id>`.

## Confirmación

La confirmación web debe estar firmada contra:

- `user_id` efectivo;
- versión del token;
- modo `account_restore`;
- schema version;
- target `user_data_restore`;
- hash estable del payload;
- hash estable del plan.

Si cambia cualquiera de esos datos, el commit debe rechazarse y el usuario debe revisar un nuevo preview.

## Operaciones

El plan debe usar operaciones explícitas:

- `insert`
- `update`
- `skip`
- `conflict`
- `invalid`
- `unsupported`

No existe éxito parcial silencioso.

## Atomicidad y auditoría

- Si el plan tiene `invalid` o `conflict`, registrar `blocked` y no escribir dominio.
- Antes de mutar dominio, registrar `pending`.
- Si falla la escritura, hacer rollback completo y registrar `failed` con una transacción limpia.
- Si el commit de dominio y auditoría no puede confirmarse completo, no debe quedar `succeeded`.
- `succeeded` solo es válido si datos de dominio y auditoría quedaron confirmados.
- `all skip` debe poder terminar en `succeeded`.

## Privacidad

No guardar ni renderizar:

- payload crudo;
- tokens;
- trazas;
- password hash;
- secretos;
- archivos binarios;
- valores sensibles innecesarios en auditoría.

La UI puede mostrar hashes truncados y conteos agregados.

## Restauración de referencias

Las referencias internas exportadas deben remapearse en memoria. En el estado actual aplica especialmente a:

- `training_plan_id`;
- `training_plan_version_id`;
- sesiones de entrenamiento ligadas a versiones históricas.

Recetas deben referenciar productos por claves seguras del usuario destino o productos incluidos en el mismo export. No se deben inventar productos o snapshots para satisfacer referencias faltantes.

## Límites de entrada

El servicio debe rechazar payloads abusivos por:

- tamaño en bytes;
- profundidad;
- cantidad de nodos;
- longitud de strings;
- tamaño de arrays;
- cantidad de claves por objeto;
- tamaño de secciones.

## Pruebas mínimas

- Preview read-only.
- Confirmación requerida.
- Token manipulado.
- Token reutilizado.
- Schema futuro rechazado.
- Límites JSON.
- Round-trip semántico completo.
- Restore repetido como skip/update explícito, sin duplicar.
- Rollback por referencia faltante.
- Aislamiento entre usuarios.
- Rutina con múltiples versiones y sesiones históricas.
- Data center e historial sin exponer payload crudo.

## Fuera de alcance actual

- Restore ZIP/binarios.
- Borrado destructivo.
- Sincronización espejo.
- API pública.
- Impersonación admin.
