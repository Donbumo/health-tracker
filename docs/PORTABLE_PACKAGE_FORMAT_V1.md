# Formato `health-tracker-portable-v1`

## Extensión Alpha 1.8

Alpha 1.8 añade las secciones opcionales `goals` (`records/goals.jsonl`) y `reminder_rules` (`records/reminder_rules.jsonl`). Las reglas conservan hora, días, timezone, quiet hours, snooze y límites, pero omiten próxima ejecución e historial. Import fija `source=portable_import`, `requires_device_confirmation=true` y no agenda en el dispositivo destino hasta revisión explícita.

## Identificación

- Extensión: `.htpack`.
- Contenedor: ZIP estándar.
- MIME: `application/vnd.health-tracker.portable+zip`.
- `format`: `health-tracker-portable-v1`.
- `format_version`: `1.0`.
- Lector mínimo: `1.0`.

La extensión no es una prueba de formato. Todo lector debe validar el contenido.

## Layout

```text
manifest.json
checksums.json
schemas/
  portable_manifest.schema.json
  portable_checksums.schema.json
  portable_inspection.schema.json
  portable_import_plan.schema.json
  portable_import_result.schema.json
  portable_<section>.schema.json
records/
  profile.json
  settings.json
  exercises.jsonl
  plans.jsonl
  workouts.jsonl
  schedules.jsonl
  sessions.jsonl
  session_exercises.jsonl
  sets.jsonl
  body_stats.jsonl
  nutrition_entries.jsonl
  custom_foods.jsonl
  steps.jsonl
  external_sources.jsonl
  attachments.jsonl
attachments/
  <portable-uuid>/<safe-ascii-name>
```

Sólo aparecen las secciones incluidas. `profile` y `settings` son JSON singular; el resto usa JSON Lines, un record por línea. Los schemas core y de cada sección incluida son obligatorios y deben coincidir semánticamente con el contrato v1 instalado.

## Canonicalización

- UTF-8 estricto, sin BOM y LF.
- Objetos JSON con claves ordenadas, separadores compactos y newline final.
- Archivos y records en orden estable.
- Fechas ISO 8601; timestamps UTC terminados en `Z` cuando corresponda.
- UUID públicos RFC 4122 en minúsculas.
- Decimales como strings base 10, sin notación binaria ni ceros finales innecesarios.
- Unidades canónicas del dominio, por ejemplo kg y metros.
- Nombres internos ASCII, POSIX, relativos y de hasta 255 caracteres.

## Manifest

`manifest.json` incluye export UUID, creación UTC, aplicación/versión de origen, timezone informativa, versión de schema por sección, incluidas/omitidas, conteos, lista de archivos con tamaño y SHA-256, política de attachments, política de redacción, warnings y lector mínimo.

No incluye username, `user_id`, host, URL, IP, ruta local, IDs internos, secretos ni datos del administrador. Email y nombre visible sólo pueden aparecer dentro de `records/profile.json` con consentimiento explícito.

Cada fila de `files` tiene `path`, `size_bytes` y `sha256`. Incluye records, schemas y binarios de attachments; no incluye `checksums.json` para evitar autorreferencia.

## Checksums

`checksums.json` fija `algorithm=sha256` y cubre `manifest.json` y todos los archivos declarados por el manifest. El lector exige igualdad exacta entre miembros ZIP, manifest y checksums antes de deserializar records.

Un checksum correcto sólo indica que los bytes no cambiaron desde que se calculó. El paquete v1 no está firmado y su autenticidad es `not_proven`.

## Envelope de record

Todo record contiene:

```json
{
  "schema_version": "1.0",
  "record_type": "body_stats",
  "public_id": "00000000-0000-4000-8000-000000000001",
  "revision": 1,
  "data": {}
}
```

`revision` es opcional cuando el dominio no tiene una revisión persistida. `data` nunca acepta identificadores internos o campos sensibles prohibidos. Los aliases externos no forman parte del contrato portable.

## Attachments

Están deshabilitados por defecto. `records/attachments.jsonl` declara UUID portable, `archive_path`, filename saneado, SHA-256, tamaño, MIME y tipo genérico. Cada binario debe existir exactamente una vez bajo `attachments/`, coincidir con metadata/checksum y pertenecer al owner exportador. No se transportan rutas originales.

## Validación segura

Antes de leer records se rechazan:

- rutas absolutas, traversal, backslash, NUL, Unicode no ASCII o ambiguo;
- duplicados exactos o por case-fold;
- directorios explícitos, symlinks y archivos especiales;
- ZIP cifrado, ratio extremo, exceso de archivos o tamaños;
- manifest/checksums ausentes o duplicados;
- miembros no declarados, archivos faltantes o tamaños/hashes distintos;
- schemas faltantes, extra, desconocidos o distintos del v1 instalado;
- secciones/versiones no reconocidas;
- UTF-8 inválido, NaN/Infinity, profundidad, strings o líneas excesivos;
- conteos incorrectos, records sobre límite y attachments sin metadata.

El lector no extrae el ZIP completo. Recorre metadata central, aplica límites, verifica streams y sólo después procesa records. Los límites predeterminados son 50 MiB comprimidos, 200 MiB descomprimidos, 256 archivos, 50 MiB por archivo, 50.000 records por sección, profundidad 20, strings de 100.000 caracteres, línea JSON de 2 MiB, attachments totales de 100 MiB y ratio 100:1 para miembros mayores de 1 MiB.

## Compatibilidad

Agregar una sección o versión requiere schema público, lector que la reconozca y política explícita de importación. Un lector v1 rechaza versiones desconocidas; no debe intentar adivinar ni normalizar un contrato futuro. Los JSON Schemas de `schemas/` son la fuente de verdad pública.
