# Android Companion Alpha 1.6

## Infraestructura de fuentes externas Alpha 1.6

Alpha 1.6 mantiene las cinco pestañas y añade **Ajustes → Fuentes externas**. Un registro desacoplado declara manual, Health Connect genérico/confirmado y Xiaomi S400 BLE experimental por `accountScope`. El diagnóstico de báscula lee solo peso/grasa con permiso y muestra tipos, conteos, fechas truncadas, estado del ledger y fingerprints; nunca valores, IDs o packages completos. Confirmar un origen como báscula/S400 es una preferencia local revocable y no reclasifica destructivamente imports anteriores.

BLE es opcional. API 31+ solicita scan/connect de forma contextual; API 26–30 limita ubicación al scan requerido por plataforma. Scan dura 15–30 s, necesita selección explícita y se cierra al seleccionar/salir/background. GATT solo descubre estructura, salvo la escritura del CCCD estándar después de que el usuario seleccione un notify/indicate para una captura debug consentida. Capturas `ble-capture-v1` se cifran con Keystore en almacenamiento sin backup, no entran en Room salvo metadata y solo se exportan mediante FileProvider/confirmación.

Room 6 conserva la cadena explícita 1/2/3/4/5→6. `ExternalMeasurementReconciler` solo auto-reconcilia identidad fuerte exacta; probabilidades conservan ambos registros. El adaptador S400 no interpreta peso, unidad, impedancia o composición y el mapper de dominio siempre devuelve ausencia. Detalle y QA pendiente: [ALPHA_1_6_EXTERNAL_SOURCES.md](ALPHA_1_6_EXTERNAL_SOURCES.md).

Cliente Android nativo y offline-first para planificar, ejecutar, registrar salud diaria, importar Health Connect en modo de solo lectura y sincronizar. El backend sigue siendo autoritativo; la app reutiliza los dominios canónicos de peso, nutrición, alimentos, energía y entrenamiento, sin duplicar `TrainingSession`, cursor, importador ni protocolo.

## Salud diaria en Alpha 1.4

Hoy conserva sus cinco destinos principales y añade tarjetas compactas de peso, nutrición, pasos y entrenamiento, con acciones rápidas que abren pantallas anidadas. `Salud del día` emite primero `daily_health_summaries` desde Room y después reconcilia, si hay red, `GET /api/v1/mobile/health/today?date=&timezone=`. La fecha seleccionada es un `LocalDate`; el servidor aplica la zona IANA recibida para evitar mover mediciones entre días.

Las rutas Bearer aditivas son:

- cuerpo: `GET/POST /api/v1/mobile/body-stats` y `PATCH/DELETE /api/v1/mobile/body-stats/<uuid>`;
- nutrición: `GET /api/v1/mobile/nutrition/days/<date>`, `POST /api/v1/mobile/nutrition/entries`, `PATCH/DELETE /api/v1/mobile/nutrition/entries/<uuid>` y `POST .../<uuid>/duplicate`;
- catálogo privado: `GET/POST /api/v1/mobile/foods` y `PATCH /api/v1/mobile/foods/<uuid>` para edición o archivado;
- pasos: `GET/POST /api/v1/mobile/steps` y `PATCH/DELETE /api/v1/mobile/steps/<uuid>`;
- progreso descriptivo: `GET /api/v1/mobile/health/progress?from=&to=&timezone=`.

Toda escritura exige `Idempotency-Key`, UUID público y revisión base al editar o eliminar. Un recurso ajeno responde 404. Los errores de conflicto solo conservan tipo, revisiones y estado sanitizado; nunca notas, alimentos, medidas o payloads.

## Health Connect en Alpha 1.5

La integración usa `androidx.health.connect:connect-client:1.1.0`, estable y compatible con `compileSdk 36`, `minSdk 26`, JDK 17 y el toolchain actual. API 26–27 queda en `unavailable_device` sin afectar login, Hoy ni el entrenamiento. En Android 13 o inferior puede requerirse instalar o actualizar el proveedor; Android 14+ usa el módulo del sistema cuando está disponible. La UI diferencia no disponible, proveedor ausente, actualización requerida, sin conectar, permisos parciales o revocados, importando, actualizado, pausado y error temporal.

La tarjeta voluntaria de **Ajustes → Health Connect** permite seleccionar tipos antes de solicitar permisos, conectar, administrar acceso, sincronizar, pedir lectura en segundo plano cuando la feature existe, pausar, desconectar sin borrar y eliminar por separado solo lo importado. Los permisos se comprueban antes de cada lectura y una revocación afecta únicamente al tipo correspondiente. Peso, grasa corporal compatible y pasos están seleccionados por defecto; nutrición es opt-in. Masa magra y masa de agua se muestran deshabilitadas porque `muscle_mass_kg` y `water_percent` no son equivalentes semánticos a masa magra y masa de agua.

`HealthConnectGateway` aísla el SDK; `AndroidHealthConnectGateway`, `HealthConnectManager` y `HealthConnectSyncCoordinator` implementan disponibilidad, permisos, páginas, agregados, Changes y errores sanitizados. La primera lectura reconcilia como máximo 30 días y crea un token por cuenta, tipo y generación de permisos. Las siguientes lecturas procesan upserts y borrados y solo avanzan el token dentro de la transacción Room que persistió el cambio. Un token expirado reabre la ventana segura sin vaciar primero los datos. Cambiar un permiso invalida solo el tipo afectado.

El ledger usa la identidad `recordType + Health Connect record ID` y conserva, por `accountScope`, client record ID/versión, origen, UUID local/servidor, modificación, fingerprint, timestamps, estado y separación por edición. Peso y grasa preservan timestamp y zone offset; grasa solo se enlaza con un peso Health Connect del mismo instante y origen. Los pasos usan `StepsRecord.COUNT_TOTAL` con `aggregate()` por fecha/zona, sin filtro de `DataOrigin`, y guardan un total `health_connect_aggregate`; el manual conserva precedencia visual sin sumarse. Nutrición solo entra si fecha, comida, nombre y al menos un nutriente son representables; no inventa porción ni macros y marca completitud.

El recorrido es Health Connect → Room/ledger → resumen Hoy/Progreso → cola servidor durable. Una repetición conserva UUID y `client_event_id`; un create ya intentado y una actualización posterior quedan en FIFO como create seguido de update rebased, por lo que el modo offline del servidor no pierde el último contenido. Si el usuario edita peso o nutrición importados, la copia pasa a `user_override`, el ledger se separa y cambios o borrados futuros del origen no la sobrescriben. No existe escritura hacia Health Connect.

## Auditoría de base

En la base `6b41d1c` no existían `android/`, Gradle, Kotlin, Compose, CI Android, OpenAPI, cliente generado ni fixtures Android. Sí existían API Auth, Mobile Sync, Companion Delivery, planned workouts, completed workouts, drafts web y las doce fórmulas de carga. Los tests de backend cubrían aislamiento, refresh/reuse, cursor, idempotencia, conflictos, package hash, completion atómica y concurrencia MariaDB.

## Matriz contractual

Abreviaturas: `B` = Bearer; `I` = `Idempotency-Key`; `R` = revisión optimista; `C` = cursor firmado por usuario/dispositivo; `O` = owner efectivo del token; `Q` = cola Room/WorkManager.

| Capacidad | Endpoint | Método | Auth | Request schema | Response schema | Revisión | Cursor | Idempotencia | Owner scope | Errores | Retry | Offline | Compatibilidad | Prueba backend | Brecha Android cerrada |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Health/conexión | `/api/v1/health` | GET | No | — | envelope + status/app | — | — | — | — | HTTP/taxonomía local | manual | No | app exacta | `test_api_v1` | URL y prueba nativas |
| Login/registro | `/api/v1/auth/login` | POST | No | login + device UUID | token envelope | — | crea estado | sesión DB | usuario autenticado | 400/401/429 | controlado | No | platform android | auth/API tests | credencial efímera |
| Refresh | `/api/v1/auth/refresh` | POST | refresh opaco | refresh | tokens rotados | familia | — | claim único | sesión/familia | reuse/revoked | single-flight | No | token v1 | concurrencia API | Keystore + mutex |
| Perfil | `/api/v1/me` | GET | B | — | perfil/capabilities | — | — | — | O | 401/revoked | tras refresh | cache mínima | campos nuevos ignorados | API v1 | cuenta actual |
| Bootstrap | `/api/v1/sync/bootstrap` | GET | B | — | `sync_bootstrap` 1.0 | entidades | C | read-only | O | schema/capability | rebootstrap | snapshot local | exige 1.0 | mobile/companion | Room transaccional |
| Pull | `/api/v1/sync/pull` | GET | B | cursor/limit | `sync_pull` 1.0 | payload | C | read-only | O | cursor/entidad | páginas, límite 20/ciclo | aplica local | campos nuevos ignorados | mobile sync | cursor único |
| Push | `/api/v1/sync/push` | POST | B+I | `sync_push` 1.0 | resultado por elemento | R | conserva C | batch + operación | O | accepted/duplicate/conflict/invalid/forbidden/unsupported | backoff+jitter | Q | límites bootstrap | mobile/MariaDB | cola durable |
| Estado sync | `/api/v1/sync/status` | GET | B | — | `sync_status` | — | C | — | O | 401 | manual | cache | 1.0 | mobile sync | diagnóstico sanitizado |
| Planned today | `/api/v1/planned-workouts` | GET | B | rango | lista 1.0 | R | por pull | — | O | fecha/404 | sync | cache | snapshot histórico | mobile sync | Hoy/siguiente |
| Historial | `/api/v1/completed-workouts` y bootstrap | GET | B | ventana/página | completed 1.0 | R | por pull | — | O | 401/404 | incremental | reciente | `weight_kg` estable | mobile sync | detalle read-only |
| Negociación | `/api/v1/companion/negotiate` | POST | B | `companion_negotiation` | selección/perfil | R perfil | comparte C | — | O+device | unsupported/conflict | explícito | perfil cache | sin downgrade | companion tests | gate de versiones |
| Preparar delivery | `/api/v1/companion/deliveries` | POST | B+I | planned UUID | `companion_delivery` | R | comparte C | I+clave natural | O+device | state/package size | replay | requiere red | 1.0 | companion/MariaDB | download action |
| Descargar package | `.../<id>/package` | GET | B | — | workout package 1.0 | snapshot R | comparte C | inmutable | O+device | expired/404 | manual | persiste normalizado | campos unsupported explícitos | companion schemas | SHA-256 canónico |
| ACK/start/abort/fail | `.../<id>/<action>` | POST | B+I | operación 1.0 | delivery | R | comparte C | client op + I | O+device | hash/state/R | Q | sí tras download | estados allowlist | companion tests | transiciones durable |
| Checkpoint | `.../<id>/progress` | POST | B+I | progress 1.0 | evento | secuencia | comparte C | event UUID + I | O+device | gap/stale/conflict | Q ordenada | Sí | escalares, no telemetría | companion/MariaDB | process death |
| Completion | `.../<id>/complete` | POST | B+I | completion + completed workout | delivery + sesión | R | emite cambio | event UUID + I | O+device | hash/revision/event conflict | Q hasta autoritativo | Sí | `weight_kg` + detalle aditivo | completion atómica | no doble submit |
| Revocación | `/api/v1/devices/<uuid>` | DELETE | B | UUID propio | revoked | sesiones | — | repetible | O | 404/session revoked | no loop | limpia local | UUID público | API tests | UX comprensible |
| Catálogo | `/api/v1/mobile/exercises` | GET | B | búsqueda + cursor | `mobile_planning` | — | consulta | read-only | O | filtros honestos | página | caché Room | aliases en detección | planning tests | buscar/seleccionar |
| Rutinas | `/api/v1/mobile/plans` y `.../<id>` | GET/POST/PATCH | B+I | agregado + revisión | `mobile_planning` | R | cursor compartido | I | O | 404/409/422 | decisión | Q | `TrainingPlanVersion` | planning tests | CRUD/orden/archivo |
| Entrenamientos | `/api/v1/mobile/plans/<id>/workouts` y `/api/v1/mobile/workouts/<id>` | POST/PATCH | B+I | agregado completo | workout read model | R | cursor compartido | I | O | límites/conflicto | FIFO | Q | doce cargas | planning tests | editor/series |
| Crear programación | `/api/v1/mobile/workouts/<id>/schedule` | POST | B+I | fecha + timezone | planned workout 1.0 | R | cursor existente | I | O | fecha/estado | FIFO | Q | snapshot | planning/companion | agenda |
| Agenda/mover/cancelar | `/api/v1/planned-workouts` y `.../<id>` | GET/PATCH + `POST .../cancel` | B; B+I en escritura | rango o fecha/timezone/revisión | planned workout 1.0 | R | cursor existente | I en escritura | O | 404/409/422 | FIFO | Q | UUID estable | planning/companion | semana/mes/Hoy |

La auditoría detectó y corrigió una divergencia aditiva: el pull real ya emitía `companion_profile` y `companion_delivery`, pero el enum de `sync_pull.schema.json` no los declaraba. El schema y una prueba funcional ahora cubren las cuatro entidades del cursor compartido.

## Arquitectura

```text
Compose/ViewModel
  → CompanionRepository
    → Room (fuente offline, accountScope)
    → cola PendingAction
      → WorkManager único
        → OkHttp + API Auth refresh single-flight
          → API v1 / Mobile Sync / Companion
```

Room normaliza cuenta, planned workouts, packages, ejercicios, sets, deliveries, drafts, checkpoints pendientes, sesiones recientes y cursor. DataStore contiene configuración no sensible. Android Keystore cifra el refresh token; el access token permanece en memoria.

Room 4 añade resumen diario, historial corporal, día/entradas nutricionales, catálogo y estado de búsqueda, pasos por fecha/fuente, conflictos y puntos de progreso, siempre con `accountScope` en la clave. La migración explícita 3→4 se encadena desde 1, 2 o 3 y no usa migración destructiva. Las unidades se convierten una sola vez hacia kg canónicos con el factor exacto `0.45359237`; si un valor mostrado no se edita, se conserva el decimal canónico original.

Room 5 añade ajustes, estado de permisos, estado incremental y ledger Health Connect, además de procedencia en Hoy/Progreso y zone offset corporal. La migración explícita 4→5 se encadena y valida desde las versiones 1, 2, 3 y 4 sin destructive migration. Tokens, selecciones, ledger y cola sobreviven a process death y se limpian únicamente con la partición de cuenta conforme a las reglas existentes.

La cola durable usa acciones `health_body_*`, `health_nutrition_*`, `health_food_*` y `health_steps_*`. Un create seguido de updates mantiene un único create con el estado final; un create nunca enviado seguido de delete desaparece localmente; updates repetidos conservan el último payload. Timeout, DNS, 429 y 5xx mantienen la operación. Los conflictos distinguen revisión, recurso ausente, validación y acceso revocado, y permiten usar servidor, reintentar, duplicar cuerpo/nutrición o cancelar el cambio local.

Alpha 1.3 agrega una proyección estructurada y owner-scoped de catálogo, rutinas, entrenamientos, ejercicios, prescripciones y conflictos en Room 3. `TrainingPlanVersion` continúa siendo el historial inmutable: cada mutación móvil publica una versión y programar crea el `PlannedWorkout`/package Companion existente. No existe un segundo cursor, calendario ni motor de ejecución.

La navegación principal pasa a **Hoy · Plan · Historial · Progreso · Ajustes**. Plan separa Rutinas y Agenda; permite crear, autosalvar, duplicar y archivar rutinas, ordenar entrenamientos, buscar ejercicios por nombre o alias, editar series y cargas, y programar/cancelar por fecha local. La agenda ofrece semana o mes y acceso rápido a Hoy.

Semana muestra siete días y Mes una cuadrícula simple con indicadores y lista del día seleccionado. Ambas leen Room, admiten varios eventos diarios y muestran etiquetas humanas para pendiente local, descargado, inicio pendiente, activo, completado, cancelado y conflicto. Mover conserva el UUID de la programación; cancelar y archivar requieren confirmación, y un plan con programaciones activas no se archiva. Hoy observa la misma fuente por la zona horaria de la cuenta, de modo que un movimiento local entra o sale sin refresh manual.

La descarga compara la revisión del package con la programación. Una revisión nueva puede reemplazar una descarga todavía no iniciada; nunca sustituye un draft activo y en ese caso abre un conflicto visible. Completion offline crea de inmediato una sesión local pendiente y actualiza Progreso, mientras la reconciliación autoritativa conserva una sola sesión por `client_event_id`.

Alpha 1.2 añade entidades Room estructuradas para páginas y detalle de historial, resumen por periodo, ejercicios, puntos temporales y mejores marcas. La UI observa Room; `GET /api/v1/mobile/history`, su detalle y `GET /api/v1/mobile/progress/*` solo refrescan/reconcilian la caché. La base sube a versión 2 mediante migración explícita que conserva `recent_sessions`; no existe una base paralela ni se guardan respuestas JSON opacas.

La navegación principal es **Hoy · Historial · Progreso · Ajustes**. Historial ofrece cursor, fechas, ejercicio y detalle read-only. Progreso cubre 7/30/90/180/365 días o todo, comparación anterior, detalle por ejercicio, mejores marcas deterministas y gráficas Canvas con resumen textual accesible. Hoy muestra únicamente un resumen semanal, la última sesión y una marca reciente.

El volumen tradicional se calcula como carga canónica por repeticiones solo para `direct_total`, `per_side`, `bar_plus_per_side`, `machine_initial_total`, `machine_initial_per_side`, `machine_external_per_side_initial_total`, `selector_stack` y `dumbbell_each`. `bodyweight`, `bodyweight_plus`, `assistance` y `duration_distance` se conservan pero no se mezclan en mejores cargas o volumen comparable.

## Estados y robustez de Alpha 1.1

Hoy distingue conexión, sincronización activa, pendientes, conflictos, descarga, start, draft activo/pausado/guardado, finalización pendiente y corrupción. Los estados internos se traducen a texto humano y la fecha operativa se presenta en formato local; el ISO queda reservado al diagnóstico sanitizado.

Las mutaciones de package/ACK, set/checkpoint, delivery, draft, historial y cola que forman una unidad visible se confirman en transacciones Room. La disponibilidad descargada es un `Flow`, por lo que Hoy ofrece **Empezar** sin esperar un pull. Start es completamente local y encola la transición; la cola impide que PROGRESS o COMPLETE adelanten un START retrasado.

Sync manual, WorkManager y triggers automáticos comparten single-flight por repositorio. Login/bootstrap, ACK, START/PROGRESS/COMPLETE, refresh, foreground y conectividad recuperada usan trabajo único, constraint de red y coalescing. Descarga, start, finalización y acciones por serie mantienen gates contra doble pulsación.

Tras process death sin red, una cuenta con refresh cifrado, scope, dispositivo y registro Room coherentes abre su cache antes de intentar red y puede reanudar un draft verificado. Los campos válidos se autosalvan a los 400 ms y se fuerzan al perder foco, navegar o ir a background. Al volver la conexión se restaura primero el access token, se revalida bootstrap/negociación cuando corresponde y después se sincroniza. Solo revocación o refresh definitivamente inválido limpian la sesión; fallos temporales nunca borran credenciales ni corrompen drafts.

## Datos y privacidad Alpha 1.7

`Ajustes → Datos y privacidad` añade portabilidad sin otra pestaña. Room 7 conserva export jobs, import jobs, inspecciones, planes, decisiones, metadata de descarga y temporales con `accountScope`. Los `.htpack` no se guardan en Room: viven en almacenamiento privado particionado por identidad de cuenta/servidor.

Export permite secciones y rango; perfil identificable y attachments parten apagados. Import usa SAF, inspección local, upload, dry-run, resumen de conflictos y confirmación. Descargar escribe `.partial`, verifica tamaño/SHA-256 y sólo después habilita guardar o compartir. FileProvider concede URI temporal y no expone el árbol BLE. Consulta [Alpha 1.7](ALPHA_1_7_DATA_PORTABILITY.md).

## Objetivos y recordatorios Alpha 1.8

`Ajustes → Objetivos y recordatorios` conserva las cinco pestañas y usa Room primero. La pantalla crea/edita/pausa/archiva objetivos, configura reglas, explica el permiso Android, envía una prueba explícita y muestra el centro local. Hoy muestra hasta tres objetivos; Progreso consume la caché 7/30/90. WorkManager y el ledger sobreviven process death; reboot sólo solicita reprogramación futura. Consulta [Alpha 1.8](ALPHA_1_8_GOALS_REMINDERS.md).

## Alcance no soportado

Alpha 1.5 integra únicamente lectura de Health Connect para los tipos documentados. Google Fit, Huawei Health, Xiaomi Home/S400, BLE, Wear OS, fotografía, OCR, IA, códigos de barras, recomendaciones y diagnósticos siguen fuera de alcance. Los objetivos de nutrición o pasos permanecen ausentes cuando el backend no tiene un contrato existente; no se fabrican valores.

Reloj, Bluetooth, escritura hacia Health Connect, sesiones/rutas de ejercicio, sueño, signos vitales, datos médicos, telemetría continua, FIT output, deep links, WebView, analytics, publicidad y vendors Garmin/Huawei/Magene siguen fuera de alcance. Los packages planeados conservan de forma aditiva carga, `load_details`, RIR, RPE y notas cuando están prescritos; clientes anteriores pueden ignorarlos.
