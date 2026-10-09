# External Exercise Catalog 1.0

Catálogo local para Gym. Fuente inicial: [yuhonas/free-exercise-db](https://github.com/yuhonas/free-exercise-db), declarada Public Domain / Unlicense. Solo el sync administrativo necesita Internet. No hay API externa en entrenamientos, descargas dinámicas, cron ni nuevos servicios.

## Auditoría y arquitectura

Base verificada: master/origin/master en `5607164f771e98b4d731da3e0100473d12ccd0a5`, working tree limpio; head anterior `20260920_0041`. No se inspeccionó NAS: verificar su estado real queda detrás del gate operativo solicitado.

| Elemento actual | Reutilización |
| --- | --- |
| `Exercise` | Identidad personal, `user_id` obligatorio, `public_id` estable y nombre propio. El sync nunca crea, renombra, reasigna ni elimina estas filas. |
| `ExerciseAlias` | Mecanismo existente de nombres importados → identidad del propietario. Confirmar un mapping guarda el nombre original aquí. |
| Resolver Gym | Usa identidades y aliases del propietario; la metadata externa se precarga en batch para la proyección visual. |
| `gym-catalog.json` | Conserva ilustraciones aprobadas y atribuciones, como fallback cuando no hay referencia externa aplicable. |
| `TrainingPlan` / `TrainingPlanVersion` | Dominio actual del programa/prescripciones. Conserva versiones, contrato `training_plan` y `Exercise.public_id`. |
| `TrainingSession` / `TrainingSessionExercise` / `TrainingSet` | Dominio actual de sesiones/performances. Sync no actualiza referencias ni contenido histórico. |
| Import Gym | Parse → draft read-only → resolver → documento estándar → validación → token owner-bound → servicio oficial `confirm_program` / `publish_program_document` → commit. |

La extensión añade `ExternalExercise`: metadata compartida, UUID propio y unicidad `(source, external_id)`. El ID externo se conserva exacto, con collation binaria en MariaDB. `Exercise.external_catalog_id` es un vínculo nullable de presentación; los ejercicios personales mantienen su propiedad.

`ExerciseCatalogSource` guarda manifest y punteros activo/anterior. La DB es la autoridad de activación, sin un symlink `current` que pueda divergir. El protocolo `ExternalExerciseCatalogSource` define source_id, source_name, source_revision, license, fetch, validate, normalize y media. Futuras fuentes pueden implementar ese protocolo y registrarse sin cambiar Gym; Wger/ExerciseDB no están implementadas.

## Metadata y contratos

No cambia el JSON público de rutinas/sesiones. `resolved_catalog_id` y `catalog_revision` son campos del draft de Gym y no se filtran al documento estándar.

| Fuente | Metadata interna | Política |
| --- | --- | --- |
| `id` | `external_id` | String original exacto; identidad inmutable por fuente. |
| `name` | `name`, `normalized_name` | Actualizable externamente; nunca renombra Exercise. |
| `force` | `details.force` | Enum nullable; opcional en fuente. |
| `level` | `details.difficulty` | beginner / intermediate / expert. |
| `mechanic`, `equipment`, `category` | Campos homónimos en `details` | Enums; mechanic/equipment aceptan null. |
| `primaryMuscles`, `secondaryMuscles` | `primary_muscles`, `secondary_muscles` | Arrays de músculos. |
| `instructions` | `details.instructions` | Texto, sin ejecutar HTML/código. |
| `images` | `media` | Referencias JSON a archivos, nunca blobs. |

Cada medio conserva source, external_exercise_id, relative_path, position, mime_type verificado, sha256, width, height y license. No hay rutas absolutas del NAS en estas filas. Validación precede a escritura; no se inventan datos para satisfacer campos requeridos.

## Resolución y confirmación

Orden de referencia externa: source + external_id (o UUID de referencia), vínculo explícito guardado, nombre canónico exacto, alias exacto único, nombre normalizado exacto único; en otro caso unresolved. Identidades y aliases personales siempre se consultan por el `user_id` efectivo del servidor. Las coincidencias múltiples no se seleccionan automáticamente.

El preview ofrece coincidencias/candidatos, selector del catálogo y «Crear nuevo», por lo que un movimiento sin referencia puede importarse como user-defined. Los candidatos por búsqueda nunca se convierten automáticamente en aliases/mappings. `prensa` ofrece resultados de `leg press` solo para revisión manual, sin afirmar equivalencia.

La confirmación guarda vínculo y alias dentro de la transacción oficial Gym. El detalle también permite elegir una identidad propia y confirmar un vínculo con POST + CSRF, conservando nombre, aliases e historial. Cambiar el snapshot entre preview y confirmación exige nueva revisión. Sync nunca guarda decisiones personales.

## Storage y descarga

Un único bind mount adicional en el Compose existente:

- Host default `~/health-tracker-data/exercise-catalog`, configurable con `EXERCISE_CATALOG_HOST_PATH`.
- Container `/app/data/exercise-catalog`, configurado mediante `EXERCISE_CATALOG_ROOT`.
- Fuera de Docker: `DATA_ROOT/exercise-catalog`, salvo override.

```text
exercise-catalog/free-exercise-db/
  .sync.lock
  <commit-sha>/
    manifest.json
    LICENSE.md
    exercises.json
    exercises/<external-id>/0.jpg
    exercises/<external-id>/1.jpg
  <commit-sha>-metadata/  # si se activó metadata-only
```

Preparar el directorio host con permisos para el usuario `app` del contenedor antes del deploy. Esta rama no modifica permisos ni volúmenes del NAS. Respaldar DB y storage juntos para recuperar vínculos y archivos. El paquete portable existente conserva nombres, aliases e historial; no transporta snapshots ni el vínculo local de presentación.

El ref se resuelve una vez a SHA completo. Full sync descarga tarball por SHA; metadata-only descarga JSON/licencia por SHA sin imágenes. No se ejecuta código upstream. Se ignora todo `site/`, incluido su symlink; fuera de ese árbol se rechazan enlaces/tipos especiales.

Límites: HTTPS con hosts permitidos, redirects deshabilitados, timeout de socket 30 s y plazo por descarga 300 s; 256 MiB comprimidos, 512 MiB declarados expandidos, 8 MiB por archivo, 12,000 miembros, 5,000 ejercicios, 10 imágenes por ejercicio y 25 megapíxeles por imagen. Se verifican content type, JSON, enums, IDs, licencia y decode JPEG/PNG. Se rechazan traversal, rutas absolutas, colisiones de mayúsculas y nombres no portables. Solo se materializan metadata/licencia/extensiones de imagen permitidas.

## Atomicidad, updates y cleanup

Lock del SO → staging → validación/normalización → publicación de directorio inmutable → transacción DB con metadata + puntero activo → cleanup. Publicar archivos antes del commit evita activar metadata con archivos incompletos. Un fallo DB conserva el catálogo anterior y puede dejar un directorio huérfano recuperable. Un fallo de cleanup posterior se reporta como `cleanup_pending`, sin declarar fallida una activación exitosa. Los locks se liberan al morir el proceso.

Se conservan actual y anterior. Cleanup explícito elimina snapshots huérfanos y staging abandonado bajo lock; nunca elimina los dos retenidos. Un item retirado upstream queda `available=false`: conserva fila/UUID/vínculos/historial, sin anunciar archivos retirados. No hay descargas al arrancar la app ni al abrir ejercicios.

## Comandos

Dentro del backend/container, con la configuración administrativa existente:

```sh
flask exercise-catalog status
flask exercise-catalog sync --source free-exercise-db --ref <commit> --dry-run
flask exercise-catalog sync --source free-exercise-db --ref <commit>
flask exercise-catalog sync --ref <commit> --metadata-only --dry-run
flask exercise-catalog cleanup
```

Dry-run solo descarga/valida en staging y lo limpia; no cambia metadata ni punteros. Metadata-only real activa una versión sin medios: usarlo deliberadamente, pues elimina imágenes de la proyección activa; un sync full puede promoverla después. Repetir revisión/modo verifica los archivos retenidos y añade cero filas. Reutilizar una revisión retenida conserva su provenance original. Status informa fuente, revisión, counts, timestamp del snapshot y espacio libre sin rutas internas.

Manifest: source, source_name, repository, commit_sha, license, downloaded_at, exercise_count, media_count, metadata_sha256, metadata_only, snapshot_bytes y archive_bytes. También se conserva `LICENSE.md` original.

## Web, medios y gate sin GitHub

- `/exercise-catalog`: búsqueda local por nombre, músculos, equipo y aliases propios; filtros por músculo/equipo/categoría/dificultad; 48 tarjetas por página.
- `/exercise-catalog/<public_id>`: demostraciones, instrucciones, músculos, equipo, dificultad, fuerza/mecánica y provenance; sin inventar semántica inicio/final.
- `/exercise-catalog/media.json`: proyección local para Gym, sin cache autenticado.
- `/exercise-media/<source>/<external_id>/<position>?revision=<snapshot>`: archivos públicos de referencia, MIME explícito, nosniff, cache de un día, ETag/304, Last-Modified y 404 controlado. Solo referencias DB dentro del snapshot activo. Una URL retirada devuelve 404 en vez de servir bytes nuevos bajo una revisión antigua.

Las imágenes usan URLs del mismo origen. Atribuciones externas son enlaces informativos, sin carga de medios remotos. Sin medio se conserva el fallback neutral. Identidades/aliases y metadata se precargan en batch, sin consultas DB por binding de imagen. No se cambió el service worker: «sin GitHub» presupone Health Tracker y MariaDB locales disponibles.

## Migración y producción

Única migración `20260927_0042` sobre `20260920_0041`: dos tablas + FK nullable. Downgrade elimina metadata/vínculos de presentación, no identidades/historial; recuperarlos exige backup. Upgrade desde cero, downgrade a 0041, upgrade, head único y db check se verificaron en MariaDB 11.4.

Esta entrega termina en rama + commit + push. No hay merge, NAS ni sync de producción. Después de review → PR → squash → master desplegado:

1. Backup obligatorio de DB/storage y verificación de head/permisos del bind mount.
2. Status → dry-run, registrando commit de fuente.
3. Sync por ese commit → counts e imágenes locales.
4. `/healthz`, rutina, sesiones, import y modal con GitHub bloqueado.
5. Revisar los seis nombres reales unresolved en la cuenta correcta, solo lectura; reportar raw name / candidatos / razón y esperar confirmación, especialmente `prensa`.

Los seis nombres reales no se consultaron ni copiaron: quedan detrás del gate NAS solicitado. No se inventan equivalencias. En la fuente verificada, `leg press` encuentra `Leg Press`, `Narrow Stance Leg Press`, `Smith Machine Leg Press` y `Calf Press On The Leg Press Machine`. El último es de pantorrilla y debe descartarse si no corresponde. No se inventaron variantes ausentes.

## Reporte de entrega

| Puntos solicitados | Evidencia |
| --- | --- |
| Fuente / revisión | Free Exercise DB, `f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5`. |
| Arquitectura / identidad / aliases | Adapter neutral, metadata global, identidades owner-only y aliases actuales; vínculo explícito nullable. |
| Storage / tamaño | Un bind mount; tarball 99,768,797 bytes; snapshot medido 99,678,299 bytes, aproximadamente 95.1 MiB; sin imágenes en Git/DB. |
| Ejercicios / medios / filas | 876 ejercicios, 1,746 imágenes en MariaDB QA; 876 filas de referencia + una fuente. |
| Performance / idempotencia | Primera descarga/decode/import: 10.219 s en este equipo; repetición offline: cero filas nuevas/duplicados. Para 12 identidades: tres consultas de precarga, cero durante bindings. |
| Schema / MariaDB | Migración 0042, ciclo upgrade/downgrade y db check exitosos en MariaDB 11.4 efímera. |
| Ambigüedad / import | `prensa` unresolved; candidatos explícitos, selector, alias confirmado, user-defined y protección contra cambios de snapshot. |
| Medios / offline | JPEG/PNG decodificados, cache/ETag/304/404 probados. Browser bloquea todo off-origin y servidor QA rechaza HTTP saliente; rutina/sesión/catálogo/search/detalle/modal/import funcionan. |
| Licencia / provenance | Unlicense en manifest, licencia original, detalle y modal; créditos anteriores intactos. |
| Search / UI | Búsqueda local, paginación, filtros y galería. |
| Tests | Suite completa: 1,098 passed, 25 skipped (gates opt-in), una advertencia de fixture ZIP duplicada. Catálogo: 33 passed en MariaDB y SQLite. JS: 8 passed. |
| Visual QA | 60 combinaciones: catálogo/search/detalle/rutina/sesión × 360/390/430/768/1024/1366 × claro/oscuro; imágenes decodificadas, sin overflow, consola limpia y cero requests externos. Capturas 390×844/1366 inspeccionadas. |
| Archivos | Modelos/migración, fuente/sync/resolver, CLI, rutas/Jinja/CSS, integración Gym, Compose, tests/scripts QA y documentación. |
| Commit / push | `feat: add local external exercise catalog`, rama `feature/external-exercise-catalog`; commit exacto en la entrega Git. |
| Bloqueadores / listo para PR | Código preparado para revisión. Gates de producción y reporte de seis nombres reales pendientes hasta autorización del NAS posterior a revisión. Sin deploy ni mappings reales. |

QA reproducible: `backend/tests/test_external_exercise_catalog.py` usa fixtures ficticias y SQLite por defecto. `CATALOG_TEST_MARIADB=exercise_catalog_unit_qa` habilita únicamente el schema desechable en loopback:33379. `scripts/gym/catalog_qa_app.py` exige directorio temporal `ht-catalog-qa-*`, usa otro schema `exercise_catalog_qa` y provee sync/serve. `scripts/gym/catalog_visual_qa.cjs` usa Playwright/Edge solo para QA; la app y el sync no requieren Node/npm.
