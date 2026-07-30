# Pruebas Android Companion

## Automatizadas

El 29 de julio de 2026, el endurecimiento del kit físico pasó en orden `lintDebug`, 93/93 JVM forzadas, `assembleDebug`, `compileDebugAndroidTestKotlin` y segunda pasada forzada 93/93. El harness externo pasó 42/42 casos bajo Windows PowerShell 5.1, incluido SDK ficticio, build-tools semántico/fijado, dispositivos/firmas/versiones, redacción y cleanup. El SDK/APK reales validaron antes de terminar con `device_missing`; no se ejecutó instalación, launch, logcat clear ni `connectedDebugAndroidTest`.

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

## QA manual requerido

Para RC1 usa [ALPHA_1_5_PHONE_QA_RUNBOOK.md](ALPHA_1_5_PHONE_QA_RUNBOOK.md): el preflight descubre SDK, inspecciona APK, selecciona dispositivo y compara certificado de forma read-only; la instalación separada exige `ALPHA15-INSTALL` y usa únicamente `adb install -r`. El smoke no toca formularios ni datos. El recorrido manual valida process death, offline/reconexión, web y permisos parciales reales; debe terminar con pendientes/conflictos en cero y sin duplicados ni secretos.

Usa únicamente cuenta y datos ficticios. Ejecuta los recorridos conectado, modo avión/process death/reconexión y errores descritos en el encargo Alpha 1.1. Cubre teléfono pequeño/medio/grande, API 26 y API 36, claro/oscuro, fuente grande, TalkBack, portrait/landscape y doble toque en completion.

Verifica específicamente 401 con refresh válido/inválido, revocación, 409 revision/submission, 422, 429 + `Retry-After`, 500, JSON malformado, schema incompatible, hash alterado, package expirado y DB/draft corruptos simulados.

El 21 de julio de 2026 pasaron `lintDebug`, `testDebugUnitTest` (34 tests, dos pasadas), `assembleDebug` y `compileDebugAndroidTestKotlin`. `connectedDebugAndroidTest` continúa pendiente porque el único AVD disponible es el Pixel_7 que conserva el caso QA manual y no debe limpiarse ni usarse para instrumentación. La matriz manual offline, rotación, tamaños, fuente grande, TalkBack, temas y HTTPS tampoco se marca aprobada.

El 25 de julio de 2026 la matriz final Alpha 1.3 pasó en orden: `lintDebug`, `testDebugUnitTest` forzado (49/49), `assembleDebug`, `compileDebugAndroidTestKotlin` y una segunda ejecución forzada de `testDebugUnitTest` (49/49). La instrumentación no se ejecutó y continúan pendientes el QA manual visual/accesible y el recorrido real modo avión→process death→reconexión en un AVD o dispositivo separado.
