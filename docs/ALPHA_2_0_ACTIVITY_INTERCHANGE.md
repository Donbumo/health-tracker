# Alpha 2.0: intercambio de actividades

Alpha 2.0 incorpora actividades de ciclismo, carrera, caminata, senderismo, fuerza e indoor mediante un pipeline auditable: archivo original → detección → parser acotado → `health-tracker-activity-v1` → inspección read-only → confirmación → importador oficial → MariaDB. FIT, GPX y TCX son entradas soportadas; JSON estándar y CSV de resumen se admiten en las herramientas de normalización. No se incluye escritor FIT ni envío a servicios externos.

## Componentes

- Alembic `20260731_0036` amplía `activities` y añade jobs de importación, laps, artefactos de series, metadatos de ruta, candidatos de duplicado, vínculos a planes y snapshots comparativos.
- La API Bearer bajo `/api/v1/mobile/activities` usa UUID públicos, ownership por el usuario autenticado, revisiones optimistas e idempotencia. Las listas y series son paginadas/acotadas.
- El archivo original se conserva en storage privado con nombre aleatorio. Las series densas y rutas comprimidas quedan fuera de la base; MariaDB conserva metadatos, hashes y referencias owner-only.
- Android code 20, `2.0.0-alpha01`, usa Room 10 y nueve entidades particionadas por `accountScope` e identidad del servidor. SAF permite seleccionar offline, calcular SHA-256, conservar permiso persistible y crear un job durable. WorkManager ejecuta un upload único por job con red, backoff y verificación de cuenta, servidor y hash.
- Web y Android muestran resumen, laps, series reducidas, ruta dibujada localmente y comparación descriptiva. No usan tiles, geocodificación ni mapas externos.

## Flujo de importación

1. Seleccionar un `.fit`, `.gpx` o `.tcx` de hasta 10 MB. Android guarda una copia parcial privada consentida y metadatos; el límite acumulado de archivos de actividad en servidor es 250 MB por usuario.
2. Detectar contenido y extensión. Ejecutables, HTML, SVG, ZIP disfrazado, XML con DTD/entidades/XInclude, XML profundo, valores no finitos y coordenadas fuera de rango se rechazan.
3. Inspeccionar tipo, tiempos truncados, conteos, métricas, ruta, warnings y clasificación de duplicado. Esta etapa no crea una actividad.
4. Confirmar. La actividad, laps, referencias de artefactos y vínculo fuerte se escriben atómicamente con el resultado idempotente.
5. Revisar duplicados probables/posibles y candidatos débiles de plan; ninguno se resuelve automáticamente.

## Dedupe y procedencia

`exact_file_duplicate` usa SHA-256 del archivo dentro de la cuenta. `exact_activity_duplicate` usa el fingerprint canónico. `probable_duplicate` y `possible_duplicate` conservan evidencia sanitizada hasta decisión humana. Consultas de otra cuenta responden 404 y no revelan si un hash existe.

Cada métrica declara procedencia como aportada por la fuente, derivada exactamente, derivada de forma estimada o no disponible. No se inventan timestamps, elevación, frecuencia cardiaca, potencia, cadencia, distancia ni calorías.

## Exportación y portabilidad

- JSON `health-tracker-activity-v1`: actividad completa; series y ruta solo con opt-in.
- CSV de resumen y laps: representación tabular con pérdida declarada.
- CSV de muestras: exige `include_series=true` y está limitado a 2,000 muestras por descarga.
- GPX: exige `include_route=true`, usa únicamente la ruta visible, conserva timestamp/elevación cuando existen y advierte métricas omitidas.
- TCX y FIT no se escriben en Alpha 2.0.
- Portable v1 incluye actividades, laps, vínculos y comparaciones en el conjunto normal. Coordenadas y series densas son dos opt-ins independientes; nunca viaja el archivo original.

## Herramientas

`scripts/activities/` contiene `inspect_activity_file.py`, `convert_activity.py`, `verify_activity_json.py` y `redact_activity_route.py`. No sobrescriben salida. Inspect no muestra coordenadas salvo `--show-sensitive-route`, que imprime primero una advertencia. Los archivos generados son artefactos locales y no deben añadirse a Git.

## Validación automatizada

- Backend local: 716 pruebas correctas, 9 omitidas por depender del contenedor y un warning histórico intencional de ZIP duplicado.
- MariaDB 11.4 efímera: 92/92 en storage temporal, incluidas carreras de idempotencia y E2E FIT/GPX, plan, exports, portabilidad, ownership y cleanup. Alembic pasó cero→0036, 0035→0036, `check`, downgrade y re-upgrade.
- Android: lint, dos pasadas forzadas de 166 pruebas JVM, APK y compilación de instrumentadas. El APK code 20/name `2.0.0-alpha01-debug` usa firma debug v2 y pasó el escaneo sensible.
- Los contenedores, red, imagen y storage QA se eliminaron; no se crearon ni eliminaron volúmenes.

## Límites y QA pendiente

La interpretación FIT autoritativa ocurre en backend; Android cachea resumen, laps y metadatos, no series densas. Fuerza solo se vincula automáticamente con referencia fuerte y la sesión estructurada sigue siendo la fuente principal. Las comparaciones son descriptivas: no recomiendan carga, FTP, recuperación ni emiten diagnósticos. Quedan pendientes QA físico/AVD, instrumentadas conectadas, archivos reales del usuario y validación manual de layouts 320/360/411/600 dp; no se declaran realizados.
