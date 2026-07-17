# Regla canónica: importación asistida de JSON no estándar

Aplica a `SchemaDetector`, `UniversalJsonImportAssistant`, `StandardJsonGenerator`, `AssistedImportService` y al preview de JSON no estándar.

Complementa `canonical-data-contract-import-update.md` y `standard-json-generator-development.md`. La propuesta original de la fase, incluidos componentes futuros y ejemplos ya superados, se conserva en `../history/PHASE_5B_ORIGINAL_PROPOSAL.md` y no define el contrato vigente.

## Responsabilidad

El flujo asistido es flexible en la entrada y estricto en la salida:

```text
JSON externo → detección/mapping → JSON estándar canónico en memoria → schema oficial → plan/preview
```

- Un JSON que valida contra un schema oficial usa el flujo estándar.
- Un JSON que no valida puede analizarse para candidatos, aliases, paths y warnings.
- El resultado generado usa únicamente nombres canónicos del schema.
- Un documento inválido por campos faltantes es un resultado válido del preview; no se inventan valores.

## Separación de escritura

Estos componentes son read-only:

- no escriben MariaDB;
- no hacen commit;
- no crean `UploadedFile`, `ImportRun` ni jobs;
- no guardan originales o generados;
- no escriben `/data`.

La escritura real pertenece al flujo confirmado descrito en `confirmed-standard-import.md` o al importador oficial aplicable.

## Contrato y aliases

- Los schemas de `../../schemas/` mandan sobre ejemplos o mappings históricos.
- Los aliases solo se aceptan en detección/normalización y deben mapearse al campo canónico.
- Ejemplo: `body_water_percent` o `water_percentage` pueden detectarse como aliases, pero el JSON estándar genera `water_percent`.
- No se agregan propiedades no soportadas para conservar aliases históricos.
- `user_id` efectivo proviene del servidor; el valor del archivo no selecciona destino.

## Preview mínimo

Debe informar, según aplique:

- candidato y confianza;
- path de origen y mapping sugerido;
- documentos generados, válidos e inválidos;
- aliases y conversiones usados;
- campos ignorados o no soportados;
- errores de schema y warnings;
- plan de operaciones sin ejecutar escritura.

No debe prometer importación, persistencia de mapping ni dominios que el código no soporte.

## Dominios vigentes

La lista real de targets se obtiene de `StandardJsonGenerator.SUPPORTED_TARGETS` y debe mantenerse cubierta por pruebas. No copies esa lista a nuevos documentos salvo que la tarea cambie el dispatch; el código y las pruebas evitan que una tabla documental quede obsoleta.

## Criterios de aceptación

1. JSON estándar detectado conserva su flujo oficial.
2. JSON no estándar produce asistencia y errores útiles, no una excepción genérica.
3. El resultado usa el contrato canónico y valida contra el schema correspondiente.
4. No se inventan requeridos ni IDs.
5. Preview no escribe DB ni archivos.
6. Paths anidados no duplican ni mezclan registros.
7. Las fixtures son ficticias.
8. Pruebas cubren estructura plana/anidada, aliases, inválidos, warnings y aislamiento cuando el flujo llega a persistencia.
