# Regla canónica: exportadores

## Contrato

- El schema oficial es la fuente de verdad para JSON canónico.
- Preview/capability es read-only.
- Generación requiere confirmación explícita en web y CSRF.
- Todo artefacto persistido pertenece a `user_id`, registra SHA256, tamaño, media type y formato.
- Toda consulta y descarga filtra por owner; IDs ajenos responden 404.

## Seguridad

- No confiar en filenames ni media types de entrada.
- No guardar paths absolutos ni servir fuera del storage generated.
- No servir symlinks ni archivos cuyo tamaño/hash difiera.
- Usar attachment y `nosniff`.
- Escapar HTML/XML y neutralizar fórmula CSV.
- No registrar payloads, datos sensibles, tokens o tracebacks.

## Capability

Cada exporter declara dominio, formato, extensión, media type, versión, warnings y pérdidas. Si faltan datos requeridos por el formato, capability debe ser false con razón concreta. No inventar FTP, potencia, coordenadas, timestamps ni métricas.

## Round-trip

Cuando exista importador oficial, el output debe reimportarse en pruebas. Solo se pueden ignorar IDs/timestamps técnicos y pérdidas declaradas por el formato. Coordenadas, distancia, duración, laps, FC, cadencia, potencia, versión, ejercicios, sets, reps y peso no se omiten silenciosamente.

## FIT de salida

No crear encoder binario propio ni archivos falsos. FIT output permanece experimental/unsupported hasta disponer de una biblioteca pequeña, mantenida y probada.
