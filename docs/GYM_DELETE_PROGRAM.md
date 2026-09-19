# Eliminar rutina

Rama `feature/gym-delete-program`, basada en master
`ff8d02a77fec4477a29aaf8c5210f287ba83b400`. Sin merge ni despliegue NAS.

## Comportamiento

En **Mi entrenamiento → Gestionar mi programa → Eliminar rutina**, independiente
de **Archivar**, se abre una confirmación con el nombre y las consecuencias.
El usuario debe escribir `ELIMINAR`. Visitar o cancelar esa página no escribe datos.

El borrado físico elimina la rutina, sus versiones y sus días editables solamente
si no tiene ninguna sesión, entrada de agenda ni borrador guardado. Se aplica tanto
a rutinas activas como archivadas. No selecciona automáticamente otra rutina activa.

Se bloquean explícitamente las sesiones en curso. También bloquean el borrado las
sesiones completadas, abandonadas o marcadas como eliminadas; la agenda cancelada,
omitida o eliminada; y los borradores caducados. Es deliberadamente conservador:
finalizar una sesión no habilita el borrado, porque deja historial. En ese caso se
puede archivar. No se purgan referencias ni registros históricos para desbloquearlo.

No se eliminan ejercicios personales, aliases, archivos importados, auditorías,
series realizadas ni históricos. No es un borrado de cuenta o de datos personales.

## Auditoría de relaciones

| Referencia | FK actual | Tratamiento |
| --- | --- | --- |
| `training_plan_versions.training_plan_id` | CASCADE | Eliminar solo versiones sin referencias protegidas |
| `training_plan_workouts.training_plan_id` | CASCADE | Eliminar prescripciones editables |
| `training_sessions.training_plan_id` / `training_plan_version_id` | CASCADE, no nulas | Bloquear; la cascada destruiría también ejercicios y series realizados |
| `planned_workouts.training_plan_id` / `training_plan_version_id` | CASCADE, no nulas | Bloquear en todos los estados |
| `workout_session_drafts.training_plan_id` / `training_plan_version_id` | CASCADE; la segunda no nula | Bloquear incluso referencias solo a una versión |
| `training_plan_versions.source_file_id` | SET NULL al borrar archivo | Borrar una versión no elimina su archivo fuente |
| `sync_changes.entity_public_id` | Sin FK a rutina | Conservar aviso de eliminación e idempotencia |

No cambian modelos, contratos JSON, constraints ni heads. **No hay migración**, ni
en MariaDB ni en Room. El head continúa siendo `20260913_0040`.

## Seguridad y concurrencia

GET/POST autenticados y owner-only; un ID ajeno responde 404. POST requiere CSRF,
confirmación exacta y revisión vigente. El servidor toma el usuario de la sesión.
Una revisión obsoleta responde 409 y exige revisar nuevamente la operación.

El servicio bloquea usuario y rutina en el orden del inicio/importación Gym,
comprueba referencias con lecturas bloqueantes y ejecuta un DELETE condicionado a
que no existan referencias protegidas, incluso si pertenecieran por inconsistencia
a otro propietario. No expone el contenido de esas referencias. Las FK de InnoDB
protegen también inserciones concurrentes. El caller confirma borrado y aviso de
Mobile Sync en una transacción; cualquier fallo revierte también las cascadas.

El aviso `training_plan/delete` usa la revisión anterior + 1 y payload nulo en el
contrato existente. Un reintento del mismo propietario y revisión devuelve éxito
sin volver a borrar ni duplicar el aviso. Otro ID o propietario devuelve 404.
Crear o duplicar desde móvil con un UUID ya eliminado del mismo propietario devuelve
409. No se introduce una política de purga de estos avisos.

## Móvil y AI

Android antes ignoraba `training_plan/delete`. Ahora lo aplica al caché de
prescripciones dentro de transacciones Room con `accountScope`. Las sesiones,
paquetes, borradores e historial locales no se eliminan con ese caché.

Si hay edición o acciones de planificación pendientes, mantiene la copia local y
los payloads, muestra conflicto y detiene esos envíos. El usuario puede duplicar la
copia con un ID nuevo o aceptar el borrado con **Usar servidor**. Esta última acción
descarta las operaciones de planificación vinculadas; las programaciones locales
todavía no enviadas quedan canceladas, conservando su snapshot. No ofrece reintentar
contra el mismo ID eliminado. Requiere una app compilada con este cambio: APKs
anteriores pueden seguir mostrando una rutina borrada en su caché.

Las lecturas de programa usadas por las capacidades AI pasan al estado sin programa
activo cuando corresponde; el historial bloqueado sigue siendo legible. No se añade
ninguna acción AI de eliminación ni se invoca un proveedor externo durante QA.

## Validación reproducible

Solo fixtures ficticias. MariaDB 11.4 en contenedor exclusivo, puerto loopback y
`tmpfs`, separado del stack local persistente. Nunca se usa `.env` ni producción.

- `backend/tests/test_gym_delete.py`: cascadas limitadas, originales conservados,
  sesiones y agenda en todos los estados, borrador sin plan directo, referencia
  inconsistente de otro propietario, ownership HTTP/servicio, CSRF, revisión,
  rollback, idempotencia, Dashboard/AI/historial y tombstone móvil sin resurrección.
- `backend/tests/test_gym_delete_mariadb.py`: carreras DELETE/DELETE y DELETE/inicio,
  FK reales y rollback de cascadas. Opt-in `GYM_QA_MARIADB`, restringido al esquema
  ficticio `gym_training_2_qa_20260913`, previamente migrado en un contenedor aislado.
- `scripts/gym/delete_qa_app.py` y `scripts/gym/delete_qa.cjs`: servidor desechable
  `127.0.0.1:8013`, datos temporales, cancelación, confirmación inválida/válida,
  bloqueo por historial/en curso, Dashboard/AI/historial y 36 combinaciones
  360/390/430/768/1024/1366 × dark/light × tres estados. Evidencias en el directorio
  temporal indicado por el script, nunca datos personales en Git.
- Android: lint, JVM, APK debug y compilación de instrumentación. La prueba Room
  añadida cubre aislamiento, cascada del caché, reintento, preservación de historial
  y conflicto offline. **Compilarla no equivale a ejecutarla**: queda pendiente en
  un AVD separado; no se ejecuta `connectedDebugAndroidTest` sobre el dispositivo
  habitual conforme a `ANDROID_TESTING.md`.

La publicación de esta rama no constituye aprobación de merge ni despliegue.

### Resultado del gate local

- Focal backend final: **17 PASS**. Focal integrado Gym/Mobile previo: **61 PASS,
  1 omitido** (el caso adicional de ownership HTTP se añadió después).
- Suite backend: **1053 PASS, 19 omitidos**, una advertencia de fixture ZIP duplicada.
  El focal final valida también los cambios de prueba posteriores a esa ejecución.
- MariaDB: **4 PASS** (tres nuevos y gate Gym existente); upgrade desde vacío,
  `db current` = `20260913_0040 (head)`, `db check` sin operaciones nuevas.
- HTTP/Playwright: **36 PASS**, cancelación y eliminación reales sobre fixtures;
  Dashboard, AI e historial HTTP 200; cero errores de consola y sin overflow.
- Android: **172 JVM PASS**, segunda ejecución forzada **172 PASS**, `lintDebug`,
  `assembleDebug` y `compileDebugAndroidTestKotlin` PASS. Instrumentación Room
  compilada, **no ejecutada**; QA de dispositivo pendiente.
- `compileall`, `git diff --check` y `docker compose config --quiet` PASS. Compose
  se validó con un archivo temporal de variables ficticias, sin leer `.env`.
