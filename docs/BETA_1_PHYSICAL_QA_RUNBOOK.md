# Runbook de QA físico posterior — Android Beta 1

La instrumentación y los recorridos automatizables ya se ejecutaron en un AVD API 36 desechable. Este documento conserva únicamente las comprobaciones que requieren interacción humana, hardware/proveedor real o un backend fake completo. Usa cuenta y archivos ficticios; no uses datos personales, NAS, Compose diario ni un dispositivo sin autorización.

## Evidencia que no debe repetirse en el teléfono

- [x] APK Beta identificada: package `io.healthtracker.companion.debug`, code 21, name `2.0.0-beta01-debug`, SHA-256 `40eafddc91bc6f83ab53aed17b87df6d3dc2bf176ef5b05ffa563f6b18751d58`.
- [x] 123/123 tests instrumentados en API 36, incluidas Room 1/2/3/4/5/6/7/8/9→10 y reapertura v10.
- [x] Upgrade real code 19/Room 9→code 21/Room 10 mediante `adb install -r`, misma firma y sin limpiar datos.
- [x] Modo avión, force-stop/reapertura, reboot, estados denegado/concedido de notificaciones y WorkManager real observados en el AVD.
- [x] Matriz automatizada de diez configuraciones y dataset Room sintético medidos con los límites documentados.

## Precondiciones físicas

- [ ] Autorizar explícitamente un teléfono o AVD separado y confirmar su identidad antes de instalar.
- [ ] Registrar solo fingerprint abreviado; no publicar serial, tokens, payloads, rutas ni datos sensibles.
- [ ] Confirmar la misma firma debug si se parte de una instalación QA anterior; no usar una APK de origen desconocido.
- [ ] Preparar backend/MariaDB efímeros y cuenta `qa-beta1@example.invalid`, sin Internet público ni servicios diarios.
- [ ] Preparar exclusivamente FIT/GPX/TCX/PDF/JPEG/PNG/JSON/CSV/BLE sintéticos.

## Recorrido offline y sincronización de extremo a extremo

- [ ] Descargar delivery/package ficticios desde el backend fake.
- [ ] Iniciar, autosalvar, pausar y completar un workout en modo avión; hacer force-stop y recuperar exactamente el mismo draft.
- [ ] Restaurar conectividad, ejecutar autosync y terminar con pendientes/conflictos en cero, una sola sesión y cero duplicados.
- [ ] Repetir con plan, health log, goal, portable, medical y activity; cubrir cancelación/retry.
- [ ] Ejecutar logout y cambio de servidor durante un worker; comprobar que ningún worker obsoleto escribe en otro scope.
- [ ] Recorrer refresh concurrente y respuestas 200/401/409/422/429/500 y payload/schema/hash inválidos.

## WorkManager, notificaciones y plataforma

- [ ] Verificar entrega real bajo ahorro de batería y restricciones del fabricante, sin polling ni loops.
- [ ] Recorrer rationale/no insistencia de `POST_NOTIFICATIONS` con interacción humana.
- [ ] Probar timezone/DST, snooze, dismiss, acknowledge, deeplink y antispam de extremo a extremo.
- [ ] Confirmar en lockscreen real que no aparecen peso, macros, resultados, ubicación, HR, potencia ni datos médicos.
- [ ] Probar Health Connect real autorizado: proveedor disponible/ausente, permisos parciales/revocados y background.

## SAF, FileProvider y temporales

- [ ] Portabilidad: chooser, permiso persistible/perdido, import/export/share, revocación y cleanup.
- [ ] Medical: PDF/JPEG/PNG mínimos, MIME correcto/falso, límite, URI perdida, process death y share.
- [ ] Activities: FIT/GPX/TCX sintéticos, tipo falso, hash, cancelación, retry y export.
- [ ] BLE: captura fake, cifrado, export temporal y cleanup sobre hardware autorizado.
- [ ] Confirmar grants read-only temporales, providers no exportados, paths mínimos, partial cleanup y cero URI/archivo cruzado entre cuentas.

## Layout y accesibilidad

- [ ] Recorrer login, server setup, Today, workout/recovery, planning, history, progress, health, Health Connect, external sources, portability, goals/reminders, medical, activities y settings.
- [ ] Cubrir 320/360/411/600 dp, portrait/landscape pertinente, font scale 1,0/1,3/2,0 y tema claro/oscuro/sistema en todas las pantallas críticas.
- [ ] Comprobar corte, overlap, scroll, botones, diálogos, contraste, color, descripciones, alternativas de gráficas y mensajes anunciables.
- [ ] Ejecutar TalkBack manual: labels, headings, focus order, estados y errores. TalkBack no está aprobado por los gates automáticos.
- [ ] Verificar rotación/process recreation sin perder selección o draft.

## Cierre físico

- [ ] Cero logout inesperado, duplicados, datos cruzados o secretos en logcat/reporte.
- [ ] Pendientes y conflictos quedan explicables y recuperables.
- [ ] APK, cuenta, fixtures, capturas y backend QA se limpian conforme a su política.
- [ ] Registrar evidencia sanitizada y no promover si queda P0/P1.

Beta 1 está lista para iniciar este QA físico controlado; no es una release final y los checks anteriores continúan pendientes hasta ejecutarse.
