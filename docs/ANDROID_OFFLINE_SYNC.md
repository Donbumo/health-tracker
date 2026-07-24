# Android offline y sincronización

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
