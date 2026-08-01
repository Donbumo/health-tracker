# Privacidad de exportación y portabilidad

## Actividades Alpha 2.0

`activities`, `activity_laps`, `plan_activity_links` y `plan_actual_comparisons` son estructuradas y reimportables con remapeo UUID. `activity_series` requiere `include_activity_series=true`. Las coordenadas de ruta requieren además `include_activity_coordinates=true`; por defecto solo viajan estado y `included=false`. El archivo FIT/GPX/TCX original, path, SHA completo, fingerprint técnico y datos de imports/jobs quedan excluidos.

## Configuración Alpha 1.8

`goals` transporta tipo, valor, periodo, días, timezone, estado y relaciones por UUID público. `reminder_rules` transporta hora, días, quiet hours, snooze y límites, y siempre requiere confirmación en destino. No se exportan eventos enviados, texto, historial, permission state, schedule, WorkManager, PendingIntent, channel IDs o ledger de dedupe.

Todo `.htpack` puede contener información corporal, alimentaria y de entrenamiento. Guárdalo en un lugar seguro. Alpha 1.7 no cifra ni firma el paquete: los checksums verifican integridad, no autenticidad o confidencialidad.

## Matriz de dominio

| Dominio | Clasificación | Consentimiento / remapeo / conflicto | Tratamiento |
| --- | --- | --- | --- |
| Actividades y laps | Incluido y reimportable | Sensible; UUID mapping y conflictos conservadores | Resumen/procedencia; ruta excluida por defecto. |
| Coordenadas de actividad | Altamente sensible y opcional | Opt-in separado `include_activity_coordinates` | Solo copia visible según keep/redact; nunca dirección. |
| Series densas | Sensible y opcional | Opt-in separado `include_activity_series` | Hasta 2,000 muestras por actividad; no archivo original. |
| Vínculos/comparaciones | Incluido si existen referencias | Remapeo de actividad/plan/link | Evidencia y resultado descriptivo, sin recomendaciones. |
| Perfil básico | Opcional y reimportable | Consentimiento adicional; update explícito | Nombre visible/email sólo si se elige; nunca username o ID interno. |
| Preferencias | Incluido y reimportable | Update de lineage compatible | Sólo unidad y timezone no sensibles. |
| Ejercicios personalizados | Incluido y reimportable | Remapeo y conflicto | UUID, aliases y perfil de carga portable. |
| Planes y versiones | Incluido y reimportable | Remapeo y conflicto | UUID públicos, snapshot de contenido y relaciones. |
| Workouts de plan | Incluido y reimportable | Remapeo y conflicto | Referencia al plan portable; no ID SQL. |
| Programaciones | Incluido y reimportable | Remapeo y conflicto | Puede limitarse por fecha; conserva estado sin borrar destino. |
| Sesiones completadas | Incluido y reimportable | Remapeo y conflicto | Relaciones a plan/versión/programación por UUID. |
| Ejercicios/series realizados | Incluido y reimportable | Remapeo y referencias | Series reciben identidad portable determinista cuando el modelo no tiene UUID. |
| Historial | Derivado | No portable | Se recalcula desde sesiones. |
| Progreso y PRs | Derivado | No portable | Se recalcula; no se exporta caché. |
| Peso y medidas | Incluido y reimportable | Sensible, remapeo y conflicto | Valores canónicos; procedencia saneada. |
| Nutrición | Incluido y reimportable | Sensible, remapeo y conflicto | Día/comidas/items; no se inventan macros. |
| Alimentos personalizados | Incluido y reimportable | Remapeo, dedupe y conflicto | Datos definidos por el usuario; sin catálogos técnicos. |
| Pasos | Incluido y reimportable | Sensible, remapeo y conflicto | Agregado diario canónico, no ledger de proveedor. |
| Uploads/generated files | Referencia u opcional | Attachments requieren opt-in | Metadata saneada; binario sólo si es propio y verificable. Generated recalculable se excluye. |
| Workout packages | Derivado/técnico | No portable | Se reconstruye desde plan/versiones/programación. |
| Device registrations | Técnico | No portable | No device secrets, sesiones o identidad del dispositivo. |
| Companion deliveries | Técnico | No portable | No ACKs, cursor, packages ni estado de entrega. |
| Health Connect ledger | Técnico | No portable | Sin record IDs, origin completo, cambios, permisos o tokens. |
| External sources | Referencia | Saneada | Sólo tipo genérico y dominios; sin identidad del proveedor. |
| BLE associations/GATT | Técnico | No portable | Sin MAC, association ID, services, characteristics o manufacturer data. |
| BLE captures | Altamente sensible/técnico | Prohibido | Nunca se incorporan al paquete. |
| Room/DataStore/WorkManager | Local/técnico | No portable | No caché, cola, cursor, token o estado del proceso. |

## Siempre excluido

Access/refresh tokens, contraseñas y hashes, cookies, sesiones, CSRF, signing keys, secretos cifrados, device authentication secrets, IDs internos, `user_id`, rutas absolutas, `/data`, host/IP/URL, logs, diagnósticos, changes tokens, record IDs completos de Health Connect y datos BLE técnicos.

La detección es recursiva al importar: un campo prohibido dentro de un objeto anidado invalida el paquete. El owner del origen no viaja; todo write usa el usuario autenticado del servidor destino.

## Logs y diagnóstico

Logs normales pueden incluir evento allowlisted, UUID truncado, estado, número de secciones, conteo total, tamaño, timestamp acotado, error code y hash corto. No registran manifest completo, contenido, nombres de alimentos, notas, peso, pasos, macros, attachments, rutas ni hashes completos.

Las herramientas de escritorio no muestran records por defecto. `--show-records` exige una acción explícita y emite una advertencia de salud.

## Retención y eliminación

Export e import temporales vencen por defecto en 24 horas. Borrar un artefacto verifica ownership y elimina únicamente archivo/metadata del job; no borra datos fuente. Android conserva descargas sólo en almacenamiento privado por `accountScope` hasta borrado explícito, logout del ámbito o cleanup de temporales. Guardar en una ubicación SAF pública o compartir requiere acción explícita y permiso temporal.

## Responsabilidad del usuario

- Revisa las secciones y desactiva perfil/attachments si no son necesarios.
- No envíes `.htpack` por canales no confiables.
- Borra copias del servidor y del dispositivo cuando termines.
- Usa `sanitize_htpack.py` para crear una copia nueva sin perfil, notas, attachments ni procedencia externa cuando necesites soporte o QA.
- No interpretes “integridad verificada” como “origen verificado”.

## Datos médicos Alpha 1.9

Estudios/paneles/resultados/metadata son secciones explícitas. Los documentos originales nunca se exportan por defecto: requieren `include_medical_attachments=true`, advertencia reforzada y sección `attachments`. No salen rutas, URI SAF, auditoría, logs, nombres sin sanear, tokens, estados clínicos inferidos ni datos de dispositivo. Una copia metadata-only sigue siendo útil y declara que el original no está disponible.
