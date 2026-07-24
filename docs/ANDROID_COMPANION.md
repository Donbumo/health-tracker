# Android Companion Alpha 1.2

Cliente Android nativo y offline-first para el flujo `planear → descargar → ejecutar → completar → sincronizar`. El backend sigue siendo autoritativo; la app no duplica `TrainingSession`, cursor, importador ni protocolo.

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

Alpha 1.2 añade entidades Room estructuradas para páginas y detalle de historial, resumen por periodo, ejercicios, puntos temporales y mejores marcas. La UI observa Room; `GET /api/v1/mobile/history`, su detalle y `GET /api/v1/mobile/progress/*` solo refrescan/reconcilian la caché. La base sube a versión 2 mediante migración explícita que conserva `recent_sessions`; no existe una base paralela ni se guardan respuestas JSON opacas.

La navegación principal es **Hoy · Historial · Progreso · Ajustes**. Historial ofrece cursor, fechas, ejercicio y detalle read-only. Progreso cubre 7/30/90/180/365 días o todo, comparación anterior, detalle por ejercicio, mejores marcas deterministas y gráficas Canvas con resumen textual accesible. Hoy muestra únicamente un resumen semanal, la última sesión y una marca reciente.

El volumen tradicional se calcula como carga canónica por repeticiones solo para `direct_total`, `per_side`, `bar_plus_per_side`, `machine_initial_total`, `machine_initial_per_side`, `machine_external_per_side_initial_total`, `selector_stack` y `dumbbell_each`. `bodyweight`, `bodyweight_plus`, `assistance` y `duration_distance` se conservan pero no se mezclan en mejores cargas o volumen comparable.

## Estados y robustez de Alpha 1.1

Hoy distingue conexión, sincronización activa, pendientes, conflictos, descarga, start, draft activo/pausado/guardado, finalización pendiente y corrupción. Los estados internos se traducen a texto humano y la fecha operativa se presenta en formato local; el ISO queda reservado al diagnóstico sanitizado.

Las mutaciones de package/ACK, set/checkpoint, delivery, draft, historial y cola que forman una unidad visible se confirman en transacciones Room. La disponibilidad descargada es un `Flow`, por lo que Hoy ofrece **Empezar** sin esperar un pull. Start es completamente local y encola la transición; la cola impide que PROGRESS o COMPLETE adelanten un START retrasado.

Sync manual, WorkManager y triggers automáticos comparten single-flight por repositorio. Login/bootstrap, ACK, START/PROGRESS/COMPLETE, refresh, foreground y conectividad recuperada usan trabajo único, constraint de red y coalescing. Descarga, start, finalización y acciones por serie mantienen gates contra doble pulsación.

Tras process death sin red, una cuenta con refresh cifrado, scope, dispositivo y registro Room coherentes abre su cache antes de intentar red y puede reanudar un draft verificado. Los campos válidos se autosalvan a los 400 ms y se fuerzan al perder foco, navegar o ir a background. Al volver la conexión se restaura primero el access token, se revalida bootstrap/negociación cuando corresponde y después se sincroniza. Solo revocación o refresh definitivamente inválido limpian la sesión; fallos temporales nunca borran credenciales ni corrompen drafts.

## Alcance no soportado

Reloj, Bluetooth, Health Connect, telemetría continua, FIT output, deep links, WebView, analytics, publicidad y vendors Garmin/Huawei/Magene siguen fuera de alcance. Los packages planeados no prometen `load_details` avanzados; la app los genera para el resultado realizado y conserva `weight_kg`.
