# Privacidad de ubicación en actividades

Las actividades pueden contener ubicación, horarios y métricas personales. Una ruta puede revelar domicilio, trabajo, hábitos y horarios aunque el título y el archivo parezcan inocuos.

## Políticas

- `keep`: conserva una copia visible completa porque el usuario lo eligió.
- `redact`: elimina los primeros y últimos N metros de la copia visible; el valor es configurable y no se activa silenciosamente.
- `drop`: importa resumen, laps y series permitidas sin ruta visible.
- Eliminar ruta: borra original extraído y copia visible de la actividad, conservando actividad, resumen y laps. El archivo subido original permanece sujeto a su política de retención y no se reescribe.

El trazado web/Android es local: una línea, inicio/final genéricos y distancia/elevación disponible. No usa tiles, geocodificación, nombres de calles, dirección postal ni llamadas de red. El recorte no intenta inferir domicilio.

## Exportación y portabilidad

JSON, GPX y portable excluyen puntos por defecto. GPX exige la acción `include_route=true` y solo usa la versión visible. Portable exige `include_activity_coordinates=true`; las series tienen un opt-in separado. El archivo original, rutas internas y hashes completos nunca se incluyen en portable.

## Diagnóstico

Logs normales pueden contener tipo, conteos, tamaño, duración redondeada, estado, código y fingerprint corto. No registran coordenadas, bounding boxes, ruta, frecuencia cardiaca, potencia, dispositivo completo, nombre completo del archivo, timestamps precisos, hash completo ni contenido FIT/XML. `--show-sensitive-route` es una acción explícita de CLI y muestra una advertencia antes de imprimir coordenadas.

No se usan datos de actividad en notificaciones de pantalla bloqueada. Todo archivo y metadato se aísla por usuario efectivo; Android añade `accountScope` e identidad de servidor.
