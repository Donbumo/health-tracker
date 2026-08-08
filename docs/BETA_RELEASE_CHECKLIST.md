# Checklist Beta 1 Android

## Freeze y contratos

- [x] Rama `beta/android-1.0-stabilization`, HEAD `1093d4d14c7aa52f180ed7d1ba17cea5437dc896` y staging vacío.
- [x] Sin Alpha 2.1 ni funciones nuevas.
- [x] Room 10, Alembic 0036 y schemas públicos sin cambio.
- [x] applicationId, firma, SDKs y toolchain conservados.
- [x] Code 21 y name `2.0.0-beta01-debug`.

## Gates automáticos

- [x] Android lint final.
- [x] JVM final forzada dos veces: 172/172, cero skips/fallos.
- [x] APK y `compileDebugAndroidTestKotlin` finales.
- [x] Harness seguro PowerShell 5.1: 60/60.
- [x] Imagen API 36 `google_apis` x86_64 no-Play instalada y verificada.
- [x] AVD desechable creado, validado y eliminado; `Pixel_7` intacto y cero teléfono físico.
- [x] Instrumentación: 123/123 aprobados, cero skips/fallos.
- [x] Room 1/2/3/4/5/6/7/8/9→10 y reapertura v10 ejecutados.
- [x] Upgrade code 19/Room 9→code 21/Room 10 con `adb install -r`, misma firma y datos ficticios preservados.
- [x] APK audit: 18.886.619 bytes, 173 entradas, v2, 19 permisos y cero hallazgos bloqueantes.

## Recorridos conectados

- [x] Modo avión real, force-stop, reapertura y restauración de conectividad.
- [x] Reboot del AVD y readiness posterior.
- [x] WorkManager real observado y cobertura de scheduler/cancelación/dedupe.
- [x] Permiso de notificaciones denegado/concedido y cuatro canales observados.
- [x] SAF/FileProvider/portabilidad cubiertos por instrumentación.
- [x] Dataset Room de 38.500 filas y consultas medidos; DB temporal eliminada.
- [x] Diez configuraciones automatizadas de layout; ajustes restaurados.
- [ ] Recorrido UI completo offline→backend fake→autosync con pendientes cero.
- [ ] SAF chooser/grants/URI perdida y variantes de archivos recorridos manualmente.
- [ ] Snooze/dismiss/acknowledge y batería/OEM recorridos de extremo a extremo.
- [ ] Todas las pantallas críticas y TalkBack manual.
- [ ] Health Connect real y teléfono físico autorizado.

## Infraestructura y repositorio

- [x] Backend/MariaDB/schemas sin cambios; evidencia previa conservada, no repetida sin motivo.
- [x] Compose diario, `.env`, `/data`, NAS y `qa-temp-alpha15*` intactos.
- [x] Worktree/APKs/fixtures/capturas/AVD temporales propios eliminados; solo reportes externos finales conservados.
- [x] Imagen SDK autorizada conservada.
- [x] `git diff --check` final verde y staging vacío.
- [x] Cero add, commit, push, merge, tag, reset, restore, checkout de archivos o cambio de rama.

Beta 1 queda lista para QA físico controlado, no para declararse release final.
