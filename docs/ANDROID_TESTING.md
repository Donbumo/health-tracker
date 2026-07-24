# Pruebas Android Companion

## Automatizadas

- Unitarias: doce modos de carga, canonical hash, redacción, clasificación temporal/definitiva de refresh, debounce + flush de autosave, coalescing de triggers y textos de estado offline/autosave.
- Instrumentación: aislamiento Room, Keystore, refresh temporal/definitivo con MockWebServer, package+ACK observable sin pull, sesión local tras process death, logout explícito, start/completion offline, autosave tardío, FIFO `START → PROGRESS → COMPLETE`, 200/409, pull repetido y single-flight manual/worker.
- Backend contractual: pull compartido valida cambios Companion contra `sync_pull.schema.json`.

```powershell
Set-Location android
.\gradlew.bat lintDebug
.\gradlew.bat testDebugUnitTest
.\gradlew.bat assembleDebug
.\gradlew.bat connectedDebugAndroidTest
```

## QA manual requerido

Usa únicamente cuenta y datos ficticios. Ejecuta los recorridos conectado, modo avión/process death/reconexión y errores descritos en el encargo Alpha 1.1. Cubre teléfono pequeño/medio/grande, API 26 y API 36, claro/oscuro, fuente grande, TalkBack, portrait/landscape y doble toque en completion.

Verifica específicamente 401 con refresh válido/inválido, revocación, 409 revision/submission, 422, 429 + `Retry-After`, 500, JSON malformado, schema incompatible, hash alterado, package expirado y DB/draft corruptos simulados.

El 21 de julio de 2026 pasaron `lintDebug`, `testDebugUnitTest` (34 tests, dos pasadas), `assembleDebug` y `compileDebugAndroidTestKotlin`. `connectedDebugAndroidTest` continúa pendiente porque el único AVD disponible es el Pixel_7 que conserva el caso QA manual y no debe limpiarse ni usarse para instrumentación. La matriz manual offline, rotación, tamaños, fuente grande, TalkBack, temas y HTTPS tampoco se marca aprobada.
