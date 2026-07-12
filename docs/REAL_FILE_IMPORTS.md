# Real file imports

Estado: Fase 5 / Alpha 0.3 en `feature/phase-5-real-importers`.

El flujo permite importar archivos reales o semi-estructurados desde `/imports/files`:

```text
upload raw -> SHA256 -> detectar -> parsear -> normalizar a JSON estándar -> preview -> confirmación firmada -> StandardImportExecutor -> ImportRun
```

## Formatos soportados

- GPX 1.0/1.1:
  - `trkpt` y `rtept`;
  - actividad cuando hay timestamps;
  - ruta cuando no hay timestamps;
  - distancia, elevación, bounds y puntos.
- TCX:
  - `Activities` como actividad;
  - `Courses` como ruta;
  - laps y trackpoints;
  - posición, tiempo, altitud, distancia, FC, cadencia y potencia cuando existen.
- FIT:
  - detector por magic `.FIT`;
  - decoder binario vendor-neutral con `fitdecode==0.10.0`;
  - validación de header, CRC, truncados y límites;
  - `file_id`, `device_info`, `sport`, `session`, `lap` y `record`;
  - semicircles GPS a grados y normalización de unidades;
  - actividad + ruta cuando hay GPS; actividad con warning cuando no hay GPS.
- CSV de pesajes:
  - coma, punto y coma o tab;
  - UTF-8 con BOM;
  - aliases español/inglés;
  - kg/lb con conversión visible en preview/tests.
- CSV de energía diaria:
  - fecha, calorías, pasos, distancia en m/km;
  - decimal punto o coma.
- JSON médico, training plan y completed workout:
  - pasan por el pipeline común cuando ya cumplen su schema interno.

## Seguridad

- Requiere login.
- CSRF en formularios.
- No acepta rutas locales del cliente.
- MIME no se considera confiable; se detecta por contenido y extensión.
- Preview no escribe datos de dominio.
- Confirmación se firma contra usuario, archivo, SHA256, target y plan.
- `user_id` efectivo viene del servidor.
- Reimportación idempotente por usuario.
- Los errores se muestran saneados, sin tracebacks ni payload crudo.

## Trazabilidad

- El raw se conserva como `UploadedFile` según la política existente.
- La escritura confirmada crea `ImportRun` mediante `StandardImportExecutor`.
- `Activity` y `Route` guardan `source_file_id`, `fingerprint_sha256`, JSON canónico, resumen y track/laps como JSON.

## Rutas

- `/imports/files`: upload, preview y confirmación.
- `/activities`: lista de actividades.
- `/activities/<id>`: detalle.
- `/activities/<id>/export.json`: export JSON.
- `/routes`: lista de rutas.
- `/routes/<id>`: detalle.
- `/routes/<id>/export.json`: export JSON.

## Limitaciones

- No hay mapa visual.
- No hay GPX/TCX export.
- No hay APIs privadas Magene/OnelapFit; solo archivos exportados.
- No se restauran binarios de uploads en account restore.
