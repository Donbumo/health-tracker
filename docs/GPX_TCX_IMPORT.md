# GPX y TCX import

## GPX

Soporte actual:

- GPX 1.0/1.1 por XML seguro básico.
- Rechazo de DTD/entidades.
- Límites de nodos y puntos.
- `trkpt` y `rtept`.
- Timestamps, elevación, distancia calculada, bounds, gain/loss.
- Con timestamps: se genera `activity`.
- Sin timestamps: se genera `route`.

## TCX

Soporte actual:

- `TrainingCenterDatabase`.
- `Activities` como `activity`.
- `Courses` como `route`.
- `Lap`.
- `Trackpoint`.
- Time, Position, AltitudeMeters, DistanceMeters.
- HeartRateBpm/Value, Cadence/RunCadence, Watts/Power, Speed.
- Namespaces por local-name.

## Limitaciones

- No hay mapa.
- No se preservan todas las extensiones propietarias.
- La normalización evita inventar timezone si el archivo no lo trae.
