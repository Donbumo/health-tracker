# Etapa 5: durabilidad de la cola de planificación

## Fallo P1

En el HEAD original de #17 (`cb664a9ace2160f2adbe46763cee7935dd688fd4`),
`headOfQueue` devolvía una copia sin reclamar la fila persistente. Una edición
durante el envío reemplazaba el payload de esa misma fila. El servidor recibía
la copia anterior y su ACK eliminaba la fila que contenía la edición nueva.
Los PATCH sufrían la misma carrera. Los ACK de programación también podían
reemplazar una fecha editada mientras la petición estaba en vuelo.

## Transiciones persistentes

`claimNextPending` selecciona la primera fila del scope, comprueba su elegibilidad,
incrementa `attemptCount` y guarda `status = sending` en una sola unidad SwiftData,
antes de devolver la petición al motor. No añade columnas ni migraciones.

| Estado de la fila | Payload y clave | Transición |
| --- | --- | --- |
| `pending`, cero intentos y sin error | Puede fusionarse | Reclamación atómica → `sending` |
| `sending`, al menos un intento | Inmutables | ACK → eliminación; interrupción → `pending`; rechazo → `conflict` |
| `pending`, con intento o error | Inmutables | Reintento de la misma petición cuando venza el backoff |
| `conflict` | Inmutables | Resolución explícita crea otra generación con clave nueva en el mismo puesto FIFO |

Las modificaciones posteriores a la reclamación generan otra operación. Los
PATCH solo se fusionan con la cola sin intentar y conservan campos anteriores,
incluido `workout_order`. No cruzan operaciones que puedan cambiar revisiones.
El ACK comprueba scope, clave, secuencia y payload; elimina solo su generación y
actualiza el estado visible en la misma transacción. Una entidad con trabajo
posterior permanece pendiente. Los reintentos cuentan reclamaciones, incluso si
el proceso termina antes de recibir una respuesta.

Al abrir el almacén tras un relanzamiento, `sending` vuelve a `pending`, conservando
intentos, bytes, clave y orden. Si el servidor ya había confirmado la petición,
su respuesta idempotente permite continuar sin duplicar la creación.

## Auditoría

| Operación | Protección |
| --- | --- |
| Crear/editar rutina | Create reclamado inmutable; PATCH posterior con revisión propia |
| Crear/guardar entrenamiento y ordenar ejercicios | Prescripción completa congelada; cambio posterior en otro PATCH |
| Reordenar entrenamientos | Conserva `workout_order`; respeta revisiones de padre e hijos |
| Programar/reprogramar | Solo el create no reclamado puede reescribirse; ACK antiguo conserva fecha nueva |
| Cancelar | No elimina un create reclamado; descarta solo el PATCH no intentado y conserva la revisión correcta |
| Resolver conflictos | Reemplazo de generación; revisión de operaciones posteriores; aceptar una entidad conserva ediciones de otros entrenamientos |
| Refrescar/remoto | `syncing` protege el caché; una eliminación remota con edición local se conserva como conflicto visible |

## Regresiones y ejecución

`PlanningInFlightIntegrationTests` usa SwiftData real, tanto en memoria como en
un archivo temporal reabierto, y barreras dentro del transporte HTTP. Cubre create
y PATCH en vuelo, dos ediciones, ACK repetido/antiguo, 503, 409, reconexión,
recuperación del proceso, orden, cancelación, múltiples entidades y aislamiento
de usuarios/servidores. No usa esperas de tiempo para provocar la carrera.

`PlanningFlaskQAIntegrationTests` se habilita únicamente mediante
`HT_PLANNING_FLASK_QA_URL=http://127.0.0.1:8026`. Usa el backend Flask efímero de QA
y datos ficticios: comprueba convergencia de create/PATCH, replay idempotente y
reintento tras un commit del servidor cuyo ACK se pierde.

La rama auxiliar `codex/nutrition-ios-integration-gates` ejecuta el HEAD exacto de
#17 en `macos-15`, Xcode 16.4, Swift Package en macOS y simulador iOS y las cuatro
pruebas UI contra Flask/SQLite temporal. Conserva logs, versiones y `.xcresult`.
El runner amplía las esperas UI y confirma el foco del teclado; conserva las
aserciones funcionales. El informe de integración registra los resultados y SHA.

No equivale a QA físico de iPhone, ejecución real de BGAppRefreshTask ni pruebas
de la app contra MariaDB en un dispositivo. No autoriza despliegue al NAS.
