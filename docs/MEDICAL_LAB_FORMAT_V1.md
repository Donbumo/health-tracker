# Formato `health-tracker-medical-lab-v1`

Formato público UTF-8 para importar un estudio de laboratorio mediante preview read-only y confirmación transaccional. No interpreta PDF ni ejecuta fórmulas.

## JSON

El objeto raíz exige:

- `format`: `health-tracker-medical-lab-v1`;
- `schema_version`: `1.0`;
- `study`: contrato `medical_study.schema.json`;
- `panels`: paneles con resultados ordenados;
- `attachments`: metadata opcional, nunca ruta o binario inline.

Cada recurso usa UUID público. Los resultados conservan `original_value`, `original_unit`, límites/texto del informe, procedencia y revisión. `numeric_value` es decimal JSON representado según schema y no admite `NaN`/Infinity. No se inventan campos requeridos, rangos, unidades ni claves canónicas.

Schemas:

- `medical_study.schema.json`;
- `medical_lab_panel.schema.json`;
- `medical_lab_result.schema.json`;
- `medical_attachment_metadata.schema.json`;
- `medical_import_preview.schema.json`;
- `medical_import_result.schema.json`.

## CSV controlado

La plantilla se obtiene con `GET /api/v1/mobile/medical-imports/template.csv`. El encabezado exacto v1 es:

```text
format,schema_version,study_public_id,study_type,title,laboratory_name,professional_name,study_date,issued_date,timezone,study_notes,state,panel_public_id,panel_name,panel_order,result_public_id,display_name,canonical_key,value_type,original_value,numeric_value,comparator,original_unit,reference_lower,reference_upper,reference_text,source_status,method,specimen,result_notes,result_order
```

Cada fila describe un resultado y repite la metadata del estudio/panel. El importador exige encabezado exacto, UTF-8, delimitador coma, máximo configurado de filas/celda y rechaza columnas desconocidas. Celdas cuyo primer carácter significativo sea `=`, `+`, `@` o un `-` no numérico se rechazan para impedir formula injection. Ninguna fórmula se evalúa.

## Flujo API

1. `POST /api/v1/mobile/medical-imports/preview` recibe multipart JSON/CSV.
2. Valida encoding, límites, forma estricta y schemas; devuelve errores por fila, clasificación de duplicado y token firmado ligado a user+hash por 15 minutos.
3. El cliente no modifica `document` después del preview.
4. `POST /api/v1/mobile/medical-imports/confirm` exige `confirmed=true`, token y documento idéntico, vuelve a validar y aplica en una transacción.
5. El resultado publica estado, UUID del estudio, conteos, clasificación y `uuid_mapping`.

Un fingerprint estructurado exacto puede omitirse idempotentemente. Coincidencias probables/posibles se advierten y se conservan; no hay fusión automática. Colisiones UUID se remapean sin depender de IDs internos.

## Portabilidad

Este formato de import médico no sustituye `.htpack`. `health-tracker-portable-v1` transporta las mismas entidades en cuatro secciones referenciadas y puede incorporar el binario como attachment únicamente con opt-in explícito. Ambos flujos mantienen preview/inspect antes de escribir y usan el importador oficial del dominio.
