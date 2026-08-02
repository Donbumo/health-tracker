# Runbook de QA físico posterior — Android Beta 1

Ningún punto de este documento está aprobado. Se ejecuta después de la estabilización, con un teléfono/AVD dedicado, cuenta ficticia, autorización explícita y sin datos personales. No usar `adb uninstall`, `pm clear`, root, `run-as`, backups, Play Store, cuentas Google, NAS ni el Compose diario.

## Precondiciones

- [ ] Confirmar APK `io.healthtracker.companion.debug`, code 21, name `2.0.0-beta01-debug` y SHA-256 publicado en el reporte temporal.
- [ ] Verificar firma con `apksigner verify --verbose`; conservar la misma firma que la instalación QA anterior.
- [ ] Confirmar que el dispositivo es el recurso QA autorizado y registrar solo fingerprint abreviado.
- [ ] Preparar backend/MariaDB efímeros y una cuenta `qa-beta1@example.invalid`; no usar Internet real.
- [ ] Preparar exclusivamente FIT/GPX/TCX/PDF/JPEG/PNG/JSON/CSV sintéticos.
- [ ] Capturar baseline de versión, login, server URL, Room, DataStore, Keystore, drafts y pendientes sin extraer datos privados.

## Upgrade conservador

1. [ ] Instalar una APK anterior reproducible con schema Room real y la misma firma.
2. [ ] Crear fixtures ficticias para cuenta, preferencias, token QA, draft, plan, schedule, health cache, Health Connect ledger, pendientes, temporales controlados y actividades.
3. [ ] Confirmar package, firma y versionCode anterior.
4. [ ] Hacer force-stop, nunca uninstall ni `pm clear`.
5. [ ] Ejecutar `adb -s <serial-verificado> install -r <beta-apk>` sin `-d`.
6. [ ] Reabrir y comprobar que no se solicita login por corrupción.
7. [ ] Verificar preservación de server URL, DataStore, Keystore QA, Room, drafts, planes, programaciones, historial, health cache, ledger y cola.
8. [ ] Confirmar ausencia de duplicados y que los archivos temporales pertenecen al scope correcto.

## Room 1→10

- [ ] Ejecutar por separado 1→10, 2→10, 3→10, 4→10, 5→10, 6→10, 7→10, 8→10 y 9→10.
- [ ] Reabrir v10 sin migración adicional.
- [ ] Verificar tablas, índices, FKs, nullability, defaults, constraints, scope, server identity, UUID, revisiones, hashes y pendientes.
- [ ] Confirmar preservación semántica de planificación, salud, Health Connect, external sources, portabilidad, engagement, medical y activities.
- [ ] Confirmar ausencia de fallback destructivo.

## Offline, process death y sincronización

- [ ] Login, refresh concurrente y doble login controlado.
- [ ] Today, descarga, inicio de workout, autosave, pausa y force-stop.
- [ ] Recrear proceso y recuperar la misma identidad de draft/package/idempotencia.
- [ ] Completar offline; confirmar draft y pendiente durables.
- [ ] Reconectar y verificar una sola sesión autoritativa.
- [ ] Repetir push/pull/refresh sin duplicados.
- [ ] Probar body, nutrition, steps, prioridad manual y Health Connect fake/real autorizado.
- [ ] Probar create/edit/pause/coalescing de goals y dedupe/reprogramación de reminders.
- [ ] Probar medical draft/document/URI/worker y activity FIT/GPX/TCX/hash/cancel/retry.
- [ ] Logout durante worker; verificar que no reaparece el scope limpiado.
- [ ] Cambio de servidor durante worker; verificar que la partición anterior no escribe en la nueva.
- [ ] Cancelación durante upload y conectividad intermitente.

## WorkManager, reboot y notificaciones

- [ ] Confirmar nombres únicos, tags, constraints, backoff e inputs scoped.
- [ ] Confirmar que no existen doble worker, doble upload, polling ni loop infinito.
- [ ] Reboot del recurso QA y reprogramación mínima.
- [ ] Permiso Android 13+ denegado/concedido, rationale y no insistencia.
- [ ] Canales, IDs, visibilidad privada y publicVersion genérica.
- [ ] Quiet hours, timezone, cambio de hora, snooze, dismiss, acknowledge, dedupe, antispam y resumen semanal.
- [ ] Confirmar que lockscreen no muestra peso, macros, resultados, ubicación, HR, potencia ni conflictos detallados.

## SAF, FileProvider y temporales

- [ ] Portabilidad: select, permiso, parcial, hash, share, revocación y cleanup.
- [ ] Medical: PDF/JPEG/PNG mínimos, MIME correcto/falso, tamaño, URI perdida, process death y share.
- [ ] Activities: FIT/GPX/TCX sintéticos, formato falso, hash, cancel, retry y export.
- [ ] BLE: captura ficticia, cifrado, export temporal y cleanup.
- [ ] Providers no exportados, paths mínimos, grants read-only temporales y sin traversal.
- [ ] Logout/cambio de cuenta no conserva URI o archivo de otro scope.

## Layout, accesibilidad y batería

- [ ] 320/360/411/600 dp; portrait y landscape pertinente.
- [ ] Font scale 1.0/1.3/2.0; tema claro/oscuro/sistema.
- [ ] Login, server setup, Today, workout/recovery, planning, history, progress, health, Health Connect, external sources, portability, engagement, medical, activities y settings.
- [ ] Sin corte, overlap, botones fuera, diálogo no cerrable ni target pequeño.
- [ ] TalkBack manual: labels, headings, focus order, estados, errores, gráficas y tablas.
- [ ] Rotación y process recreation sin perder selección/draft.
- [ ] Consumo de batería y restricciones OEM sin polling continuo.

## Cierre

- [ ] Sin logout inesperado.
- [ ] Sin duplicados, datos cruzados ni secretos en logcat/reporte.
- [ ] Pendientes/conflictos explicables y recuperables.
- [ ] APK/AVD/fixtures/reportes QA limpiados conforme a su política.
- [ ] Registrar fallos y evidencias sanitizadas; no promover si queda P0/P1.
