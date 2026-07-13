# Exports de Activity y Route

## Activity

- JSON: contrato `activity.schema.json` validado.
- CSV: resumen, track o laps en archivos separados; UTF-8 con BOM y columnas estables.
- GPX 1.1: `trk/trkseg/trkpt`, elevación, tiempo y extensiones allowlisted para FC, cadencia, potencia, velocidad y distancia.
- TCX Activity: `Activities/Activity/Lap/Track/Trackpoint`, posición, FC, cadencia y extensiones de velocidad/potencia.

## Route

- JSON: contrato `route.schema.json` validado.
- CSV: un punto por fila.
- GPX 1.1: política `rte/rtept`, incluso cuando los puntos tienen timestamp.
- TCX Course: `Courses/Course/Track/Trackpoint`.

No se exportan DTD, entidades ni XML crudo de entrada. Los nombres pasan por escape XML y los CSV neutralizan celdas que empiecen con `=`, `+`, `-` o `@`.

## Round-trip y tolerancias

Las pruebas vuelven a pasar GPX/TCX por los importadores reales. Deben conservar coordenadas, orden, timestamps, laps cuando el formato los representa, FC, cadencia y potencia. Distancia y elevación recalculadas aceptan una tolerancia relativa del 15 % por diferencias de redondeo/algoritmo geodésico; coordenadas usan tolerancia absoluta de `1e-6` grados.

Metadata de dispositivo y warnings internos se declaran como pérdida cuando el formato no tiene un campo interoperable.
