# FIT import

Health Tracker importa archivos FIT binarios estándar mediante `fitdecode==0.10.0`.

El soporte es vendor-neutral: se trabaja con archivos exportados por dispositivos o aplicaciones, no con APIs privadas, scraping ni credenciales de Magene/OnelapFit.

## Detección y seguridad

- Detección por magic `.FIT`.
- Validación de header y CRC.
- Rechazo de archivos truncados o con header inválido.
- Límite de records para evitar archivos excesivos.
- Campos desconocidos se ignoran sin romper el import.
- Errores saneados, sin payload crudo ni traceback.

## Mensajes FIT soportados

- `file_id` y `device_info` para manufacturer/product cuando existen.
- `sport` para sport/sub_sport.
- `session` para resumen principal.
- `lap` para laps.
- `record` para trackpoints.

## Campos normalizados

El parser genera `activity` y, cuando hay GPS, también `route`.

Campos cubiertos cuando existen:

- tipo de actividad;
- inicio/fin;
- duración y moving time;
- distancia;
- calorías;
- FC promedio/máxima;
- cadencia promedio/máxima;
- velocidad promedio/máxima;
- potencia promedio/máxima;
- ascenso/descenso;
- manufacturer/product;
- laps;
- trackpoints con timestamp, lat/lon, elevación, FC, cadencia, potencia, velocidad y distancia.

Las coordenadas FIT se convierten desde semicircles a grados. Las unidades ya decodificadas por `fitdecode` se conservan en metros, segundos, m/s, kcal, bpm, rpm y watts.

## Sin GPS

Si el FIT no contiene puntos GPS, se crea solo `activity` con track métrico y un warning. No se inventa una ruta.

## Fixtures QA

Las fixtures en `examples/qa/real-file-imports/` son binarias FIT sintéticas:

- `valid_activity.fit`;
- `valid_activity_no_gps.fit`;
- `valid_activity_unknown_field.fit`;
- `truncated.fit`;
- `invalid_crc.fit`;
- `invalid_header.fit`.

Se pueden recrear con:

```powershell
..\..\..\.venv\Scripts\python.exe .\generate_fit_fixtures.py
```

No contienen datos reales.
