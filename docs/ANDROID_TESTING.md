# Pruebas Android Companion

## Beta 1

Beta 1 mantiene las regresiones JVM de cancelación, nombres opacos y UTF-8, y añade persistencia inmediata de refresh token, clasificación portable de ZIP inválido, fixtures Room vigentes y esperas MockWebServer acotadas. El harness de `scripts/beta/` pasa 60/60 aserciones en PowerShell 5.1, incluidos fallback SDK, rechazo de Play/teléfono/`Pixel_7`/serial ambiguo, cleanup limitado, stderr nativo, timeout, reportes externos y conteo JUnit correcto.

El 1 de agosto de 2026 pasó el gate final en orden: `lintDebug` (62,282 s), JVM forzada 172/172 (41,066 s), `assembleDebug` (2,444 s), `compileDebugAndroidTestKotlin` (1,319 s) y segunda JVM forzada 172/172 (32,587 s). Después se ejecutaron realmente 123/123 métodos instrumentados en 22 clases sobre un AVD API 36 `google_apis` x86_64 no-Play: 123 aprobados, 0 omitidos, 0 fallidos, 33,151 s. Esta ejecución incluye Room 1/2/3/4/5/6/7/8/9→10 y reapertura v10.

También pasó un upgrade reproducible code 19/Room 9→code 21/Room 10 con `adb install -r`, misma firma y datos ficticios preservados. La APK Beta final mide 18.886.619 bytes y tiene SHA-256 `40eafddc91bc6f83ab53aed17b87df6d3dc2bf176ef5b05ffa563f6b18751d58`. Resultados y límites: [Android release readiness](ANDROID_RELEASE_READINESS.md); pendientes humanos: [runbook físico Beta 1](BETA_1_PHYSICAL_QA_RUNBOOK.md).

## Alpha 2.0

Las JVM cubren extensión FIT/GPX/TCX, rechazo de doble extensión, hash corto y nombre único de WorkManager por cuenta/servidor/job. Las instrumentadas compilables cubren Room 9→10, cadena 1→10, preservación y aislamiento de un UUID repetido por cuenta e identidad de servidor. Los tests backend cubren el contrato multipart, jobs durables, dedupe, privacidad, linking y portabilidad.

Gate obligatorio: `lintDebug`, JVM forzada, `assembleDebug`, `compileDebugAndroidTestKotlin` y segunda JVM forzada. `connectedDebugAndroidTest` no se ejecuta. Quedan para AVD/dispositivo aislado: permiso URI persistible/perdido, process death durante upload, modo avión→reconexión, cancelación real de WorkManager, FileProvider/chooser, TalkBack, rotación, temas, fuente grande y layouts 320/360/411/600 dp con fixtures ficticias.

El 31 de julio de 2026 pasó el gate final en ese orden: `lintDebug`, 166/166 JVM forzadas, `assembleDebug`, `compileDebugAndroidTestKotlin` y segunda pasada forzada 166/166. El APK mide 18.197.013 bytes, tiene SHA-256 `C32AC0352FDE62EC9144BABEB4A38667E0C9E2E818289E451CC2839AADED21D7`, firma debug v2 y code 20/name `2.0.0-alpha01-debug`. No se instaló ni se ejecutaron pruebas conectadas.

## Alpha 1.8

La cobertura JVM prueba DST con y sin horario estacional, overlap/gap, dedupe lógico, quiet hours, cooldown, límites, permiso contextual, contenido genérico/privado y política de resumen semanal. Las instrumentadas compilables cubren cadena Room 1/2/3/4/5/6/7→8, preservación 7→8, identidad de servidor, coalescing offline y ledger ante doble worker. No ejecutar `connectedDebugAndroidTest` en este gate; quedan reboot, permisos y entrega bajo ahorro de batería para QA físico.

## Alpha 1.6

Las JVM cubren registro de fuentes, fingerprint, diagnóstico Health Connect sin valores/IDs, permisos por API, dedupe exacto/probable/posible/detached/override, límites de scan/captura, parser/replay, propiedades notify/indicate y adaptador S400 sin publicación. Instrumentadas compilables cubren migraciones 1/2/3/4/5→6, aislamiento de scope, permisos manifest, BLE opcional y FileProvider privado.

El 28 de julio de 2026 pasó el gate final Alpha 1.6 en orden: `lintDebug`, 146/146 JVM forzadas, `assembleDebug`, `compileDebugAndroidTestKotlin` y segunda pasada forzada 146/146. `connectedDebugAndroidTest` no se ejecutó. El APK resultante mide 18.719.697 bytes y tiene SHA-256 `45f6dc75925612c6f84927270009a752b061679f383500c0f13c990235df5ac4`.

Fixtures `ble_capture_*_fictional.json` son inventadas. `connectedDebugAndroidTest` continúa prohibido en el gate automático; scan, CompanionDeviceManager, CCCD, timeout, background, cifrado/export y UI deben recorrerse después en AVD/teléfono separado con datos QA. Los comandos obligatorios permanecen lint, JVM forzada, APK, compilación androidTest y segunda JVM forzada, además de `compileall` y `--help` de las tres herramientas BLE.

## Automatizadas

- Unitarias: doce modos de carga, canonical hash, redacción, clasificación temporal/definitiva de refresh, debounce + flush de autosave, coalescing de triggers y textos de estado offline/autosave.
- Alpha 1.2: decode de contratos, porcentaje con base cero, escala de gráfica vacía/un punto/valores iguales/múltiples, caché Room owner-scoped, paginación y reconciliación sin duplicados.
- Instrumentación: aislamiento Room, Keystore, refresh temporal/definitivo con MockWebServer, package+ACK observable sin pull, sesión local tras process death, logout explícito, start/completion offline, autosave tardío, FIFO `START → PROGRESS → COMPLETE`, 200/409, pull repetido y single-flight manual/worker.
- Backend contractual: pull compartido valida cambios Companion contra `sync_pull.schema.json`.
- Alpha 1.3: orden/prescripción, semana/mes y bisiesto, zona horaria sin mover el día, programación offline con UUID estable y coalescing, varios eventos diarios, Today inmediato, package vigente/desactualizado con draft protegido, conflictos resolubles, completion local en Historial/Progreso, account scope y migraciones backend/Room 2→3.
- Alpha 1.4: conversión kg/lb sin deriva, macros incompletos, gráficas con cero/uno/múltiples puntos, caché diaria owner-scoped, cuerpo/nutrición/pasos offline, coalescing y doble pulsación, conflictos sanitizados/resolubles, logout aislado y migraciones Room 1/2/3→4.
- Alpha 1.5: 31 casos con gateway/store fake para disponibilidad, actualización de proveedor, permisos parciales/revocados, peso y grasa, mapeos incompatibles, pasos agregados/origen opaco/zona, nutrición incompleta, dedupe, Changes/token expirado, borrado/detached, rollback, process death, cuentas, single-flight, background, pausa/desconexión, borrado selectivo, cola servidor y actualización observable. Las instrumentadas de migración cubren 1/2/3/4→5.
- RC1 añade URL con puerto/base path, rechazo de credenciales/query/fragmento, separación HTTP debug/HTTPS release, cambio confirmado de servidor, binding del token al servidor, DNS/refused/timeout/TLS/HTTP sanitizados, diagnóstico Health Connect allowlisted y preservación de plan/draft/historial/salud/pendientes en 4→5. Las pruebas instrumentadas se compilan, pero no se marcan ejecutadas.

```powershell
Set-Location android
.\gradlew.bat lintDebug
.\gradlew.bat testDebugUnitTest
.\gradlew.bat assembleDebug
.\gradlew.bat compileDebugAndroidTestKotlin
.\gradlew.bat testDebugUnitTest
```

`connectedDebugAndroidTest` no forma parte de la validación automática Alpha 1.3: requiere un AVD separado y sigue pendiente junto con la matriz visual/accesible manual. Compilar `compileDebugAndroidTestKotlin` sí es obligatorio y no toca el AVD manual.

La misma restricción aplica a Alpha 1.4: no se ejecuta instrumentación conectada sobre el AVD manual existente. Debe usarse después un AVD separado para validar process death, modo avión→reconexión, rotación, TalkBack, fuente grande, temas y 320/360/411/600 dp.

Alpha 1.5 conserva esa restricción: `connectedDebugAndroidTest` no se ejecuta. El QA pendiente requiere un AVD o dispositivo separado con Health Connect y fixtures ficticias para permisos parciales/revocados, instalación/actualización del proveedor, zona horaria, background disponible/no disponible, eliminación en origen, edición detached, process death y servidor offline→reconexión. También debe inspeccionarse el merged manifest y la rationale de permisos en API 28, 33, 34 y 36.

El 26 de julio de 2026 pasó la matriz final Alpha 1.5 en orden: `lintDebug`, `testDebugUnitTest`, `assembleDebug`, `compileDebugAndroidTestKotlin` y segunda invocación de `testDebugUnitTest`; una pasada adicional `--rerun-tasks` confirmó la segunda ejecución real. El resultado es 84/84 JVM, incluidos 31 casos Health Connect. Backend pasó `612 passed, 3 skipped`; MariaDB 11.4 efímera pasó upgrade/check/downgrade/re-upgrade y 3 carreras de concurrencia. `connectedDebugAndroidTest` no se ejecutó.

El 27 de julio de 2026 RC1 repitió el orden completo sobre las brechas NAS: `lintDebug`, 91/91 JVM, APK, compilación androidTest y segunda pasada forzada 91/91. Backend local final pasó 618/3 y el focal final de proxy/readiness/smoke 9/9; Docker/MariaDB pasó 619/1 con las tres carreras. El smoke final recorrió HTTP real contra Flask efímero y limpió sus fixtures. QA real y `connectedDebugAndroidTest` continúan pendientes.

El 26 de julio de 2026 pasaron `lintDebug`, dos ejecuciones de `testDebugUnitTest` (53/53), `assembleDebug` y `compileDebugAndroidTestKotlin`. Las pruebas instrumentadas de migración 1/2/3→4 compilan, pero no se marcarán ejecutadas hasta disponer del AVD separado.

## Alpha 1.7

Automatizado JVM/instrumentación compilable:

- consentimiento de perfil/attachments, rango inválido y rutas ZIP inseguras;
- migraciones Room 1/2/3/4/5/6→7 aditivas con cuenta, pending action y draft preservados;
- aislamiento/cleanup por `accountScope`, incluida la cola durable `pending_apply`;
- inspección local válida, traversal, checksum inválido y autenticidad no demostrada;
- FileProvider content URI y separación de archivos por cuenta.

QA manual pendiente: solicitud offline→reconexión, doble toque, process death, URI persistible/perdido, descarga interrumpida, hash erróneo, guardar/compartir/borrar, paquete inválido, preview/conflictos/decisiones, confirmación, TalkBack, rotación, tamaños 320/360/411/600 dp y estados vacío/error/offline. `connectedDebugAndroidTest` no forma parte del gate automatizado de esta tarea.

El 30 de julio de 2026 pasó el gate Alpha 1.7 en orden: `lintDebug`, JVM forzada 149/149, `assembleDebug`, compilación de androidTest y segunda JVM forzada 149/149. Las instrumentadas no se ejecutaron. Backend local terminó 643/4; Docker/MariaDB terminó 645/1 más la carrera portable focal 1/1.

## QA manual requerido

Para RC1 sigue exactamente el gate de [ALPHA_1_5_NAS_RC_RUNBOOK.md](ALPHA_1_5_NAS_RC_RUNBOOK.md): `adb devices -l`, `adb install -r <apk>` y lanzamiento con `monkey`, sin uninstall ni `pm clear`. El recorrido de 30 pasos valida NAS, process death, offline/reconexión, web y permisos parciales reales. Debe terminar con pendientes/conflictos en cero y sin duplicados ni secretos en logcat.

Usa únicamente cuenta y datos ficticios. Ejecuta los recorridos conectado, modo avión/process death/reconexión y errores descritos en el encargo Alpha 1.1. Cubre teléfono pequeño/medio/grande, API 26 y API 36, claro/oscuro, fuente grande, TalkBack, portrait/landscape y doble toque en completion.

Verifica específicamente 401 con refresh válido/inválido, revocación, 409 revision/submission, 422, 429 + `Retry-After`, 500, JSON malformado, schema incompatible, hash alterado, package expirado y DB/draft corruptos simulados.

El 21 de julio de 2026 pasaron `lintDebug`, `testDebugUnitTest` (34 tests, dos pasadas), `assembleDebug` y `compileDebugAndroidTestKotlin`. `connectedDebugAndroidTest` continúa pendiente porque el único AVD disponible es el Pixel_7 que conserva el caso QA manual y no debe limpiarse ni usarse para instrumentación. La matriz manual offline, rotación, tamaños, fuente grande, TalkBack, temas y HTTPS tampoco se marca aprobada.

El 25 de julio de 2026 la matriz final Alpha 1.3 pasó en orden: `lintDebug`, `testDebugUnitTest` forzado (49/49), `assembleDebug`, `compileDebugAndroidTestKotlin` y una segunda ejecución forzada de `testDebugUnitTest` (49/49). La instrumentación no se ejecutó y continúan pendientes el QA manual visual/accesible y el recorrido real modo avión→process death→reconexión en un AVD o dispositivo separado.

## Alpha 1.9

JVM cubre decimales finitos, cálculo mecánico de rango, conversiones exactas/versionadas y comparabilidad por método. AndroidTest compilable añade Room 8→9, cadena 1→9, preservación de pending action, aislamiento por cuenta+servidor y contrato MockWebServer de Bearer/idempotencia. `connectedDebugAndroidTest` permanece prohibido. QA manual pendiente: SAF persistido/perdido, upload parcial, process death, FileProvider/share, offline→reconexión, duplicados/conflictos, logout/cambio de servidor, accesibilidad, rotación, temas y 320/360/411/600 dp.

El 31 de julio de 2026 pasó el gate Alpha 1.9 en orden: `lintDebug`, JVM forzada 157/157, `assembleDebug`, `compileDebugAndroidTestKotlin` y segunda JVM forzada 157/157. Las instrumentadas no se ejecutaron. El APK debug mide 20.513.670 bytes, usa code 19/name `1.9.0-alpha01-debug`, firma v2 y SHA-256 `05E624AAE2137F063BD4B3866665DB03FF36DA6FFB109C54AF865F63F770E6F7`; el inventario no contiene fixtures médicas ni paquetes de prueba.
