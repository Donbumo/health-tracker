# Android offline y sincronización

## Cola de engagement Alpha 1.8

Objetivos, reglas y eventos técnicos usan tipos `engagement_*` en `pending_actions`. Create→update reemplaza el payload del create, create→delete elimina ambos y múltiples updates conservan el estado final. `SyncWorker` drena esta familia antes del FIFO histórico y luego refresca objetivos, reglas y adherencia. Room emite sin HTTP desde recomposición; el trabajo de red conserva constraints y backoff existentes.

Las seis tablas nuevas incluyen `accountScope` e identidad SHA-256 del servidor. Logout cancela los works del scope antes de limpiar sus filas; el cambio de servidor no reutiliza identidad ni agenda reglas del servidor anterior.

Room es la fuente durante el entrenamiento. Un package descargado se verifica excluyendo `package_hash`, ordenando claves recursivamente y calculando SHA-256 sobre JSON canónico; solo entonces se normaliza en tablas de package/ejercicio/set.

## Flujo durable

1. Bootstrap guarda snapshot y cursor en una transacción.
2. Download crea delivery, verifica package y guarda package + delivery ACK/ACK pendiente en una sola transacción. La consulta observable de Room habilita **Empezar** inmediatamente, sin pull adicional.
3. Start no hace HTTP: crea draft y sets con IDs estables, conserva delivery/package/hash y encola la transición idempotente.
4. Cada serie se guarda localmente. Al completarla se incrementa una sola secuencia y se encola el checkpoint exacto con UUID e idempotency key estables.
5. Completion conserva el mismo `client_event_id`, package hash y revisión; no borra el draft hasta respuesta autoritativa.
6. WorkManager procesa FIFO estricto `ACK → START → PROGRESS → COMPLETE`; una operación en backoff o conflicto bloquea sus sucesoras. Después ejecuta pull incremental con el cursor compartido.

Reabrir la app recupera el draft por cuenta/delivery/package. Un draft incompatible o corrupto se marca y se aísla; nunca se mezcla con otra cuenta. La retención inicial es siete días, pero un completion pendiente no se poda automáticamente.

No existe last-write-wins: conflictos de revisión, secuencia o submission se conservan con la copia local y requieren refresh/decisión. Un error nunca guarda el payload completo como diagnóstico.

WorkManager usa trabajo periódico único cada quince minutos y trabajo inmediato único con `NetworkType.CONNECTED`. Login/bootstrap, ACK, cada operación durable, refresh, conectividad recuperada y foreground disparan la misma pipeline. Los triggers ambientales se coalescen durante cinco segundos; los durables no se descartan. Si llegan durante un worker, este absorbe la nueva generación sin ejecutar sync simultáneas. No hay polling, foreground service permanente ni peticiones por cada tecla.

Un reinicio de proceso sin red no fuerza un falso “token vencido”: si persisten servidor, scope, dispositivo, cuenta local coherente, elegibilidad offline y refresh cifrado, la UI abre inmediatamente la cache autorizada. No ejecuta bootstrap ni muestra login antes de presentar Hoy. Al reconectar renueva la sesión, valida bootstrap, negocia si falta un perfil compatible y sincroniza.

Timeout, DNS, conexión rechazada, 429 y 5xx conservan refresh, scope, Room y borradores. Solo logout explícito, refresh definitivamente inválido, credenciales ausentes/ilegibles o revocación confirmada eliminan la sesión local. Una incompatibilidad de servidor bloquea la red, pero no se disfraza de fallo temporal.

Peso, modo/unidad de carga, reps, RIR, RPE, notas, duración, distancia, descanso y resumen usan autosave Room con debounce de 400 ms. Focus loss, navegación, pausa, completion y background fuerzan flush. No se encola red por carácter. El autosave nunca revierte una serie completada, su secuencia ni estados `paused`, `pending_sync` o finales. Checkpoint + set + hash + operación pendiente se escriben atómicamente. La confirmación autoritativa aplica delivery/history/draft y elimina la cola en una transacción local.

## Historial y progreso en Alpha 1.2

Room 2 mantiene por `accountScope` páginas de historial, detalle normalizado de ejercicios/series, resumen de progreso, lista y puntos por ejercicio, mejores marcas y timestamps. Un timeout nunca elimina una versión anterior. El refresh reemplaza por UUID dentro de una transacción y reconcilia una sesión local pendiente por `client_event_id`, evitando duplicados cuando llega el UUID autoritativo.

Foreground, completion, pull con `completed_workout`, conectividad y WorkManager comparten el single-flight existente. La sesión completada se inserta localmente antes de la red con estado pendiente; al confirmar se conserva el detalle, cambia a `synced` y se invalidan/refrescan historial y periodos frecuentes. El botón manual sigue siendo respaldo.

## Planificación en Alpha 1.3

Room 3 mantiene por `accountScope` catálogo, rutina, entrenamientos ordenados, ejercicios, series y conflictos. Crear, autosalvar, duplicar, reordenar, archivar, programar y cancelar escribe primero la vista local y después encola una `PendingAction` con UUID e idempotency key. No se hace una petición por carácter ni se avanza el cursor antes de confirmar sus cambios.

La identidad del plan y entrenamiento abiertos se conserva en `SavedStateHandle`; tras recrear el proceso se recupera la misma pantalla y el contenido vuelve a observarse desde Room. Cerrar sesión elimina esa selección para no trasladarla a otro `accountScope`.

El FIFO existente procesa planificación junto con Companion. Un 409 conserva la copia local y muestra dos decisiones: usar servidor o reintentar la copia local. El pull `training_plan` reemplaza una rutina solo si no hay edición local pendiente; planned workouts continúan por su entidad histórica. Logout elimina únicamente la partición de la cuenta efectiva y sus cascadas.

Programar crea primero un UUID estable y una tarjeta `locally_pending`. Antes del primer intento remoto, `CREATE → RESCHEDULE` se consolida en un solo CREATE con la fecha final, `CREATE → CANCEL` elimina la entidad y la operación local, y varios RESCHEDULE conservan el último destino. Cuando una operación ya pudo alcanzar al servidor no se descarta: las dependencias posteriores mantienen FIFO, revisión e idempotency key persistidas. Un mutex limitado a mutaciones de agenda evita la doble programación sin bloquear el resto de la aplicación.

Hoy observa Room por la fecha operativa de la cuenta y refleja de inmediato altas, movimientos y cancelaciones locales. Una finalización offline inserta una única sesión pendiente en Historial y recalcula los resúmenes locales de Progreso de 7, 30, 90, 180 y 365 días y todo el historial; la confirmación por `client_event_id` sustituye esa copia sin duplicarla.

Un package solo se reutiliza si corresponde a la revisión vigente de la programación. Si existe una revisión nueva se reemplaza de forma transaccional antes de iniciar; un draft activo conserva su package inmutable y genera `package_revision_conflict`. Los conflictos `revision_conflict`, `archived_remote`, `deleted_or_unavailable`, `schedule_date_conflict` y `package_revision_conflict` guardan únicamente revisiones y resúmenes sanitizados. Usar servidor, reintentar con la revisión remota, duplicar cuando aplica o cancelar la copia local son decisiones explícitas; ninguna hace last-write-wins silencioso.

## Registro de salud en Alpha 1.4

Room 4 es la fuente inmediata de resumen diario, cuerpo, nutrición, alimentos, pasos, conflictos y tendencias. Todas las tablas nuevas incluyen `accountScope`; `clearAccount` elimina únicamente esa cuenta y logout continúa siendo el único borrado automático. Cerrar el proceso no borra filas ni operaciones pendientes.

Las creaciones offline generan UUID e idempotency key estables. Cuerpo, nutrición y pasos mantienen una revisión local monotónica y un estado discreto (`pending`, `syncing`, `synced` o `conflict`). La cola hace coalescing solo cuando no rompe dependencias: create→update compacta el estado final, create→delete nunca enviado elimina ambos, y updates sucesivos conservan el último estado. WorkManager reutiliza el trabajo único con `NetworkType.CONNECTED`, backoff y single-flight; no existe polling.

El resumen y Progreso se recalculan en la misma transacción que cada escritura local. Los macros incompletos permanecen nulos y solo se suman valores presentes. Los pasos manuales y los importados coexisten por fecha/fuente; la corrección manual tiene precedencia de presentación sin borrar la fuente importada.

Un fallo temporal conserva la cola. Los rechazos permanentes crean un conflicto sanitizado sin payload. Desde Salud del día se puede descartar la copia local y refrescar servidor, reintentar con una nueva idempotency key, duplicar cuerpo/nutrición cuando procede o cancelar. Ninguna resolución hace merge genérico de notas.

## Portabilidad en Alpha 1.7

Una solicitud de export equivalente se coalesce en Room y queda `pending` hasta recuperar red. WorkManager procesa exports e imports pendientes con retry para fallos transitorios; no marca el paquete como listo sin respuesta autoritativa.

La inspección estructural de un URI SAF funciona offline y persiste hash, formato, secciones, conteos y warnings. Upload/apply requieren red. El permiso URI persistible y el plan Room permiten reanudar tras process death; si el permiso se pierde, se debe elegir el archivo otra vez. Parciales fallidos se borran y el hash final gobierna la promoción. Logout limpia filas y archivos sólo del `accountScope` efectivo.

## Health Connect en Alpha 1.5

La lectura Health Connect tiene su propio trabajo único, mutex y backoff; no comparte la restricción de red de la cola servidor. Conexión, permiso concedido, foreground, selección, acción manual y periodicidad de seis horas se coalescen. Sin permiso de background el trabajo periódico termina sin leer y los triggers foreground continúan disponibles. Pausar o desconectar no revoca permisos ni borra filas importadas.

Room 5 persiste ajustes, permisos observados, token por tipo/generación y ledger por `accountScope`. La primera reconciliación pagina 30 días; Changes aplica upserts/borrados y avanza el token en la misma transacción. Si expira, repite la ventana con dedupe por ID. Para pasos, el token solo detecta que hubo cambios y entonces se recalculan de forma segura los 30 días con `aggregate(COUNT_TOTAL)`; si no hubo cambios solo avanza el token. Un fallo de transacción no avanza estado.

Cada importación válida actualiza el recurso local y Hoy/Progreso antes de encolar `health_body_*`, `health_nutrition_*` o `health_steps_*`. Un alta nunca intentada absorbe cambios posteriores. Si el alta ya pudo alcanzar el servidor, se conserva y se añade un update durable; al confirmarse el alta se actualiza su `base_revision` antes de procesar la siguiente acción. La cola se vuelve a consultar en cada paso FIFO para que esa revisión no quede obsoleta.

Un borrado del origen elimina solo el recurso todavía importado y encola el DELETE idempotente. Borrar grasa limpia ese campo sin borrar el peso asociado. Una copia `detached/user_override` permanece y pierde la asociación activa. El borrado selectivo de Ajustes recorre únicamente ledgers importados activos en una transacción; no toca registros manuales, sesiones, planes ni copias editadas.
