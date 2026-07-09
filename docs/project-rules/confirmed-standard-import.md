# Regla canónica: importación estándar confirmada

Esta regla aplica a la fase posterior a Fase 5B.

Fase 5B sigue siendo read-only:

- detección;
- mapping asistido;
- generación estándar;
- validación contra JSON Schema.

La escritura real debe vivir en un servicio separado. En el estado actual ese servicio es `StandardImportExecutor`.

Implementación actual: `StandardImportExecutor` usa adaptadores de persistencia internos por dominio para mantener un único commit transaccional del lote. No llama importadores oficiales que ejecutan `db.session.commit()` internamente, porque eso rompería la atomicidad global. Si en una fase futura se refactorizan importadores oficiales, deben aceptar un modo `commit=False` o compartir adaptadores sin commit propio.

## Separación obligatoria

El flujo debe mantenerse separado:

1. Detección.
2. Preview.
3. Generación estándar.
4. Validación.
5. Plan de importación.
6. Confirmación explícita.
7. Ejecución transaccional.
8. Resumen final.

`StandardJsonGenerator`, `UniversalJsonImportAssistant` y `AssistedImportService` no deben escribir DB, guardar archivos ni ejecutar importación real.

## Contrato de operaciones

El plan de importación debe usar operaciones explícitas:

- `insert`
- `update`
- `skip`
- `conflict`
- `invalid`

No se debe sobrescribir silenciosamente. Si el update no es seguro para un dominio, el servicio debe devolver `conflict` o rechazar la operación con error claro.

## Confirmación y seguridad

- El commit exige confirmación explícita.
- En web, la confirmación debe requerir autenticación y CSRF.
- La confirmación web debe estar ligada al usuario autenticado, al target, al payload y al plan revisado. Si cambia cualquiera de esos elementos, el usuario debe revisar un nuevo preview antes de escribir.
- Los tokens de confirmación deben ser temporales, firmados y de un solo uso práctico para evitar replay accidental durante QA.
- El `user_id` efectivo viene de la sesión/argumento del servidor.
- El `user_id` incluido en un archivo nunca puede cambiar el destino.
- Ningún usuario puede consultar, deduplicar o actualizar contra datos de otro usuario.
- No aceptar rutas locales arbitrarias.
- No ejecutar contenido del JSON.
- No exponer trazas al usuario final.

## Validación

Antes de escribir:

1. Validar de nuevo contra schema.
2. Validar pertenencia por `user_id`.
3. Construir plan completo.
4. Bloquear commit si hay `invalid` o `conflict`.

La validación del preview no sustituye la validación del commit.

## Atomicidad

El lote debe ser atómico por defecto:

- si un elemento falla antes del commit, no se escribe ninguno;
- si ocurre una excepción durante la escritura, se hace rollback;
- si el fallo ocurre después de escribir o hacer `flush` de elementos previos, el rollback debe dejar la DB sin cambios parciales del lote;
- no aceptar éxito parcial silencioso.

Si se agrega auditoría persistente futura (`ImportJob`, `ImportRun` o similar), requiere migración aprobada explícitamente.

## Deduplicación e idempotencia

Usar claves seguras del dominio:

- IDs propios del usuario cuando existan.
- Claves naturales ya documentadas por modelos/importadores.
- Huellas estables si el dominio ya las usa.

Una importación repetida no debe crear duplicados; debe resultar en `skip` o `update` explícito.

No inventar claves naturales. Si no hay clave segura, devolver `conflict` o implementar un importador de dominio explícito.

Notas actuales de dominio:

- `recipe_bundle` se planea y ejecuta por receta embebida. Cada operación conserva `recipe_index` para trazabilidad del preview.
- `completed_workout` bloquea updates como `conflict` mientras no exista una clave de actualización segura.
- Updates parciales deben aplicar solo campos presentes y no borrar campos opcionales ausentes.

## Soporte real actual por target

| Target | Insert | Repetición idéntica | Update seguro | Batch | Notas |
| --- | --- | --- | --- | --- | --- |
| `weigh_in` / `weigh_in_batch` | Sí | `skip` | Sí, parcial por `user_id + recorded_at + source` | Sí | Campos ausentes no borran valores existentes. |
| `food_product` / `food_products` | Sí | `skip` | Sí, parcial por `user_id + name + brand` | Sí | Campos ausentes no borran macros/notas existentes. |
| `daily_energy` | Sí | `skip` | Sí, parcial por `user_id + date` | Sí | Campos ausentes no borran fuente/notas/métricas. |
| `daily_nutrition` | Sí | `skip` | Sí, parcial por `user_id + date` | Sí | Reemplaza comidas solo si `meals` está presente. |
| `training_plan` | Sí | `skip` | Sí, crea nueva versión por `user_id + name` | Sí | `description` ausente no borra la existente. |
| `completed_workout` | Sí | `conflict` | No todavía | Sí | No hay payload persistido ni clave segura de update; se bloquea. |
| `medical_lab` | Sí | `skip` | Sí, parcial por `user_id + date + laboratory_name` | Sí | Reemplaza marcadores porque `markers` es requerido. |
| `recipe` | Sí | `skip` | Sí, parcial por `user_id + name` | Sí | Reemplaza ingredientes porque `ingredients` es requerido. |
| `recipe_bundle` | Sí, por receta | `skip` por receta | Sí, por receta | Sí | No existe modelo Bundle persistente; el resumen usa `recipe_index`. |

## Web QA

La ruta web mínima actual es:

```text
GET/POST /imports/standard
```

Flujo esperado:

1. Usuario autenticado sube JSON.
2. Sistema analiza y genera preview.
3. Sistema muestra plan.
4. Usuario confirma.
5. Servicio ejecuta transacción.
6. Sistema muestra resumen final.

No existe restore completo de usuario en esta fase.
