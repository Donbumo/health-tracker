# Regla canónica: real file imports

Esta regla aplica a FIT, GPX, TCX, CSV y otros archivos externos no-JSON estándar.

## Separación obligatoria

El flujo debe conservar fases separadas:

1. Upload raw.
2. SHA256.
3. Detección.
4. Parsing.
5. Normalización a JSON estándar.
6. Validación contra schema.
7. Preview read-only.
8. Confirmación firmada.
9. Commit transaccional mediante `StandardImportExecutor`.
10. Auditoría con `ImportRun`.

Los parsers no deben escribir DB. `RealFileImportService` tampoco debe saltarse `StandardImportExecutor`.

## Seguridad

- Login obligatorio.
- CSRF en confirmación.
- No aceptar paths arbitrarios.
- No confiar en MIME.
- No ejecutar contenido.
- No renderizar XML/CSV/FIT crudo.
- No exponer tracebacks.
- No usar `user_id` del archivo como destino.
- No mezclar dedupe entre usuarios.

## Dedupe

- Mismo archivo para el mismo usuario: `UploadedFile` duplicado.
- Mismo contenido canónico actividad/ruta: `skip`.
- Usuario distinto: no deduplica ni revela existencia.
- El fingerprint no debe depender de `source_file_id`.

## FIT

- FIT se decodifica con `fitdecode==0.10.0`.
- Validar magic/header, CRC, truncado y límites antes de confirmar.
- No inventar GPS, deporte, tiempos, distancia ni dispositivo.
- Si hay GPS suficiente, generar `activity` + `route`.
- Si no hay GPS, generar solo `activity` con warning.
- Campos FIT desconocidos no deben romper el import.
- Magene/OnelapFit solo se consideran soportados cuando exportan FIT/GPX/TCX estándar compatible; no usar APIs privadas ni scraping.

## XML GPX/TCX

- Rechazar DTD y entidades.
- Aplicar límites de nodos/puntos.
- No mostrar XML crudo en templates.
- `TCX Activities` genera actividad.
- `TCX Courses` genera ruta.
