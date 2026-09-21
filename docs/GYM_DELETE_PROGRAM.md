# Eliminar rutina — gate final

Rama `feature/gym-delete-program`, base master `ff8d02a77fec4477a29aaf8c5210f287ba83b400`.
Este gate sustituye la limitación del commit `886c9d8`: **tener historial ya no bloquea eliminar una rutina**. Sin merge ni NAS.

## Semántica definitiva

**Mi entrenamiento → Gestionar mi programa → Eliminar rutina** es independiente de Archivar. Muestra nombre, consecuencias y confirmación exacta `ELIMINAR`. GET y Cancelar no escriben. La acción es irreversible desde la app.

| Situación | Resultado |
| --- | --- |
| Nunca utilizada, sin referencias | Borrado físico de rutina, versiones y días editables |
| Sesiones completadas/abandonadas, incluso marcadas como eliminadas | Desaparece de Mis rutinas; identidad histórica y revisiones conservadas con `deleted_at`; días editables retirados |
| Sesión en curso | HTTP 409 hasta revisarla en `Pendientes`; se puede descartar individualmente con confirmación explícita |
| Agenda pendiente `planned` no eliminada, o `in_progress` | HTTP 409 hasta descartarla individualmente; el tombstone queda para sincronización |
| Agenda completada, omitida, cancelada o eliminada | No bloquea; snapshots y referencias intactos. Una entrada omitida no puede reactivarse contra una rutina eliminada |
| Borrador guardado, incluso caducado o enlazado solo a versión | HTTP 409 hasta descartarlo individualmente; nunca se elimina automáticamente |

No es otro archivado: no cambia `status` a `archived`, no aparece en listas activas ni archivadas, no puede editarse, activarse, programarse ni iniciar sesiones; enlaces operativos responden 404. No se elige otra rutina activa automáticamente. Sus registros internos solo sostienen el historial y las exportaciones.

Sesiones, ejercicios realizados, series, pesos, repeticiones y fechas permanecen intactos. Se conservan catálogo personal, aliases, archivos fuente y auditorías. En el caso sin uso no quedan versiones/días de planificación; permanecen auditorías y el aviso de eliminación necesarios para sincronización e idempotencia.

## Pendientes antes de eliminar

Si la rutina tiene una sesión `in_progress`, una agenda `planned`/`in_progress` o un borrador servidor, la pantalla de eliminación enlaza a **Revisar pendientes**. Cada fila se resuelve por separado mediante POST con CSRF y exige escribir `DESCARTAR`. La sesión pendiente se elimina junto con su actividad parcial y series; la agenda se tombstonea como cancelada; el borrador se elimina. Las sesiones completadas o abandonadas no se muestran ni se descartan desde este flujo. Tras resolver todos los pendientes, la confirmación `ELIMINAR` sigue siendo necesaria para quitar la rutina.

## Relaciones y migración

| Relación existente | Política |
| --- | --- |
| Plan → versiones / días editables | CASCADE; borrado físico solo sin referencias protegidas |
| Sesión → plan / versión | CASCADE, no nulas; conservar el plan histórico evita esas cascadas |
| Agenda → plan / versión | CASCADE, no nulas; referencias y snapshots conservados |
| Borrador → plan / versión | CASCADE; versión no nullable; cualquier borrador bloquea |
| Versión → archivo fuente | SET NULL al borrar archivo; borrar versión no borra archivo |
| `SyncChange.entity_public_id` | Sin FK al plan; conserva tombstone y reintentos |

Migración aditiva **`20260920_0041`**, desde `20260913_0040`: añade únicamente `training_plans.deleted_at` nullable. No modifica FK ni copia sesiones a tablas nuevas. Los registros existentes siguen con valor nulo. El downgrade se permite sin rutinas eliminadas retenidas; si existen, se rechaza antes de modificar la tabla para impedir su resurrección silenciosa.

El estado de eliminación se conserva en registros abiertos del export de cuenta/backup ZIP y paquetes portables mediante el campo opcional `deleted_at`. Los backups anteriores siguen admitidos. Los round-trips nuevos preservan historial y eliminación. No cambia el schema de entrenamiento ni la forma de las respuestas Mobile Planning/Sync.

## Seguridad y transacción

Usuario efectivo de sesión/Bearer, IDs ajenos 404, POST con CSRF, confirmación y revisión vigente. Una revisión obsoleta devuelve 409. Locks usuario → plan, lecturas bloqueantes y guardas de referencias evitan perder datos en carreras. Referencias inconsistentes de otro propietario bloquean sin exponerlas.

Borrado físico o marca histórica, retirada de prescripciones editables y tombstone se confirman en una transacción. Un fallo revierte todo. Tombstone `training_plan/delete`, revisión anterior + 1, payload nulo. Repetir la misma confirmación devuelve éxito sin duplicar efectos. Crear/duplicar con UUID eliminado del mismo usuario se rechaza; una copia nueva usa identidad nueva.

## Android

Esta corrección histórica no añade campos a Mobile Planning/Sync ni cambia Room. Usa el mismo tombstone del commit anterior. El código Android incluido en la rama retira caché sincronizado de prescripciones y conserva sesiones, paquetes, borradores e historial. Ante trabajo pendiente, conserva copia y muestra conflicto para duplicarla o aceptar el borrado; no reintenta el ID eliminado.

La prueba `CompanionDatabaseTest#deletedPlanRemovesOnlySyncedPrescriptionCacheAndPreservesOfflineConflict` se **ejecutó y pasó** en `GymDeleteQA`, AVD separado API 36. Cubre aislamiento, eliminación de caché, idempotencia, historial y conflictos. No queda pendiente esa prueba Room. No equivale a validar todos los dispositivos físicos. APKs anteriores que ignoraban tombstones requieren la actualización ya incluida en esta rama. No se instaló nada en un teléfono real ni se usó el AVD habitual.

## Evidencia y pruebas

- UI Playwright a 390 × 844 y 36 combinaciones responsive/tema sobre MariaDB 11.4 desechable, tmpfs y fixtures ficticias.
- Caso A: borrado desde UI; plan ausente, cero versiones y días exclusivos.
- Caso B: borrado desde UI; desaparece del listado; documento completo de sesión idéntico antes/después; detalle histórico HTTP 200; FK válidas; consulta histórica AI preservada; Dashboard y página AI HTTP 200. Sin proveedor AI externo.
- MariaDB: concurrencia DELETE/DELETE y DELETE/inicio; rollback físico e histórico; replay y tombstone único. Upgrade y `db check` sin diferencias al nuevo head.
- Focales de seguridad, agenda, borradores, historial, rutas operativas, Mobile Sync, backup/restore y portabilidad con aislamiento.
- Regresión transversal por cambio de modelo. Una prueba de agenda usaba fecha fija fuera del rango por defecto: se hizo explícito agosto de 2026 en el test, sin cambiar producto.
- `compileall`, `git diff --check` y Compose con variables ficticias. Sin leer `.env`, tocar contenedores persistentes ni datos reales.

Scripts: `scripts/gym/delete_qa_app.py` (con `GYM_QA_MARIADB` solo admite loopback:33079 y esquema QA permitido) y `scripts/gym/delete_qa.cjs`. Capturas y JSON en el temporal indicado. `__qa/delete-gate` solo existe en el servidor QA de loopback, nunca en la app productiva.

### Resultado final (2026-09-20)

- Backend completo: **1057 PASS, 20 omitidos**, advertencia conocida de fixture ZIP duplicada.
- Focal historial/restore/Companion: **63 PASS, 1 omitido**; gate combinado MariaDB/eliminación/sync: **33 PASS, 1 omitido**, incluidos **5 casos MariaDB**.
- UI MariaDB A/B y **36 combinaciones responsive PASS**, sin errores de consola ni overflow.
- Android: **1 prueba Room instrumentada PASS**, cero fallos, AVD QA API 36 separado.
- Migración: upgrade/downgrade/re-upgrade PASS en esquema vacío; rechazo de downgrade con referencias históricas PASS. Head `20260920_0041`, `db check` PASS.
- Compilación Python, Compose y diff-check PASS. Contenedor y AVD QA retirados después del gate.
