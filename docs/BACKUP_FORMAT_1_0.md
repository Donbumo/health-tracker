# Formato de backup completo 1.0

`backup_format_version: "1.0"` es el contrato público inicial de backup integral de Health Tracker.

## Layout

```text
manifest.json
account/user_data_export.json
raw/<logical-id>/<safe-name>
generated/<logical-id>/<safe-name>
```

No se aceptan directorios explícitos, entries adicionales, rutas absolutas, letras de unidad, `..`, barras invertidas, links ni colisiones por mayúsculas/minúsculas.

## Manifest

El contrato formal está en [`../schemas/full_backup_manifest.schema.json`](../schemas/full_backup_manifest.schema.json). El manifest incluye versión, fecha, revisión de la app, ID informativo de la cuenta origen, ruta del export, entries, totales, capabilities, unsupported y warnings.

Cada entry declara `logical_id`, `kind`, path relativo, nombre original saneado, media type informativo, tamaño, SHA256, referencia de origen informativa, obligatoriedad y metadata allowlisted. Ningún ID del origen concede autoridad durante restore.

Kinds 1.0:

- `account_export`: exactamente uno y required.
- `raw_upload`: contenido de un `UploadedFile`; required.
- `generated_export`: bytes de un `ExportRecord` ready; optional.

No se incluyen password hashes, credenciales, cookies, tokens, paths absolutos, stack traces ni payloads de auditoría.

## Límites 1.0

- ZIP comprimido: 100 MB.
- Total descomprimido: 500 MB.
- Entry individual: 100 MB.
- Entries declaradas: 2,000.
- Profundidad de path: 6 componentes.
- Ratio de compresión máximo: 100:1 para entries mayores de 1 MB.
- Manifest: 1 MB.
- Export de cuenta: 10 MB.

Los ZIP cifrados y las versiones futuras se rechazan. Cifrado de backup queda fuera de 1.0; no se implementa cifrado casero.

## Compatibilidad

La política es estricta: un lector 1.0 rechaza `backup_format_version` desconocido. Una ampliación compatible debe versionar el contrato y documentar migración/negociación antes de aceptarse.
