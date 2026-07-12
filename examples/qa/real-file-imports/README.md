# QA fixtures: real file imports

Fixtures ficticias para probar `/imports/files`. No contienen datos reales de usuario, dispositivo ni salud.

Orden sugerido:

1. `activity_track.gpx` -> debe crear una actividad.
2. Repetir `activity_track.gpx` con otro nombre -> debe ser `skip`.
3. `route_only.gpx` -> debe crear una ruta.
4. `activity.tcx` -> debe crear una actividad.
5. `course.tcx` -> debe crear una ruta desde un TCX Course.
6. `valid_activity.fit` -> debe crear actividad + ruta.
7. Repetir `valid_activity.fit` con otro nombre -> debe ser `skip`.
8. `valid_activity_no_gps.fit` -> debe crear solo actividad con warning.
9. `valid_activity_unknown_field.fit` -> debe importarse ignorando campo FIT desconocido.
10. `truncated.fit`, `invalid_crc.fit`, `invalid_header.fit` -> deben rechazarse.
11. `weigh_in_es.csv` -> pesaje en kg.
12. `weigh_in_en_lb.csv` -> pesaje con conversión lb a kg.
13. `energy_es_semicolon.csv` -> energía diaria.
14. `malformed.csv` -> debe fallar o mostrar filas inválidas.

## FIT

Los `.fit` incluidos son binarios FIT sintéticos y decodificables por `fitdecode`.

`generate_fit_fixtures.py` recrea las fixtures FIT desde cero:

```powershell
..\..\..\.venv\Scripts\python.exe .\generate_fit_fixtures.py
```

El set cubre header/magic, CRC, truncado, unidades, semicircles GPS, laps, records, dispositivo, actividad con GPS, actividad sin GPS y campos FIT desconocidos.
