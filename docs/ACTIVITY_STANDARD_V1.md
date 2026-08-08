# Estándar `health-tracker-activity-v1`

El contrato público está en `schemas/activity_v1.schema.json`; sus componentes son `activity_summary_v1`, `activity_lap_v1`, `activity_series_v1` y `activity_route_v1`. Los nombres canónicos viven en los schemas. Los aliases de FIT/GPX/TCX/CSV solo existen dentro de detección y normalización.

## Topología

- `format` y `formatVersion` identifican el documento.
- `activity` contiene UUID público, disciplina, tipo original, instante inicial, fechas/offset conocidos, entorno, estado, fuente y revisión.
- `summary` es un mapa de métricas. Cada entrada incluye `value`, `unit` y `provenance`.
- `laps`, `intervals`, `events`, `sampleSeries`, `route` y `sourceReference` son secciones explícitas. Una sección ausente o vacía no autoriza inventar información.
- `series` y `route.points` pueden aparecer en una exportación explícita. Los metadatos siguen indicando conteo y disponibilidad cuando los puntos no se incluyen.

## Métricas y unidades

El resumen admite duración/elapsed/moving en segundos, distancia y desnivel en metros, calorías en kcal, frecuencia cardiaca en bpm, cadencia en rpm, velocidad en m/s y potencia en W. Los valores deben ser finitos y estar dentro de los límites del schema. `source_provided`, `derived_exact`, `derived_estimate` y `unavailable` distinguen origen; una conversión de unidad no cambia la procedencia de la observación.

Las muestras usan tiempo relativo `t` cuando puede demostrarse, además de distancia, elevación, velocidad, frecuencia cardiaca, cadencia, potencia o temperatura disponibles. El orden incorrecto se conserva de forma controlada con warning; los gráficos usan downsampling determinista que retiene extremos.

## Laps, rutas y referencias

Un lap conserva índice, tiempos, duración, distancia, métricas y procedencia disponibles. La ruta contiene solo coordenadas válidas, elevación/distancia/tiempo relativo existentes y una política `keep`, `redact` o `drop`. Recortar produce una copia visible y nunca modifica el original.

`sourceReference` puede nombrar formato, aplicación, dispositivo sanitizado y UUID del archivo original. Nunca contiene rutas de filesystem, token, `user_id` interno ni payload FIT/XML.

## Validación

Los schemas usan JSON Schema 2020-12 y referencias locales. No se aceptan NaN/Infinity, placeholders para cumplir requeridos ni campos inventados. La secuencia válida es generar → validar → inspeccionar → confirmar → importar. `verify_activity_json.py` verifica contrato, fechas, límites y checksum sin mostrar datos sensibles por defecto.
