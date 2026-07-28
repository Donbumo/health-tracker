# Handoff activo

## Estado actual

- Alpha 1.5 RC1 está preparada en `feature/alpha-1.5-health-connect` sobre `dab0bc381a89d839c9154755e58ce07598a75d3a`, con cambios sin commit. No hacer commit, push, merge ni tag desde este handoff.
- Android conserva Alpha 1.1–1.5, applicationId release `io.healthtracker.companion`, debug `.debug`, versionCode 15, versionName `1.5.0-alpha01`, min SDK 26 y target/compile 36.
- URL NAS admite HTTPS, puerto y base path normalizados; rechaza credenciales/query/fragmento. HTTP RFC1918/loopback/`.local` exige debug y confirmación. No hay IP de servidor predeterminada.
- **Cambiar servidor** exige confirmación, cancela workers, invalida tokens/scope activos y conserva Room antigua aislada. El refresh cifrado queda ligado a la URL normalizada y las sesiones Alpha previas se enlazan una vez al servidor ya persistido.
- Red distingue DNS, rechazo, timeout, TLS y HTTP con mensajes sanitizados. Solo refresh inválido/reuse, revocación o logout limpian sesión; fallos temporales conservan offline.
- Flask confía en `X-Forwarded-For/Proto` solo con conteos 0–2 configurados; default 0 mantiene local. El runbook exige backend accesible solo desde el proxy cuando se habilita.
- `scripts/release/alpha15_nas_preflight.sh` es no destructivo. `alpha15_smoke.py` es read-only por defecto; write exige `QA-ALPHA15-WRITE`, usa fixtures ficticias y verifica limpieza.
- El diagnóstico Health Connect compartible incluye solo versión, Android, estado/tipos, conteos, timestamps y códigos sanitizados.
- Runbook vigente: `ALPHA_1_5_NAS_RC_RUNBOOK.md`. El mapa canónico sigue siendo `DOCUMENTATION_INDEX.md`.

## Base preservada

- Alpha 1.1 conserva API Auth, Keystore, packages, drafts, FIFO y offline; Alpha 1.2 historial/progreso; Alpha 1.3 planes/agenda; Alpha 1.4 salud manual; Alpha 1.5 Health Connect opt-in read-only.
- Room 5 no usa fallback destructivo. La prueba 4→5 conserva plan, draft, historial, salud y pendientes; 1/2/3→5 siguen explícitas. DataStore y Keystore permanecen fuera de Room.
- Backend mantiene un solo head `20260726_0032`, owner derivado del Bearer y coexistencia manual/Health Connect con `client_event_id` owner-scoped.

## Trabajo en curso

- QA NAS y teléfono real permanece pendiente y no está aprobado. Usar cuenta/datos ficticios, backup externo y ventana sin escrituras.
- Recorrido corto: 1–6 instalar con `adb install -r`, configurar NAS/login/process death/Hoy/descarga; 7–13 offline, serie, process death, draft, completion, reconexión y autosync.
- 14–20 crear/programar plan, confirmar Hoy, capturar peso/comida/pasos y verificar una copia en web.
- 21–26 conectar Health Connect, conceder peso+pasos, importar/procedencia, revocar pasos y comprobar que peso continúa.
- 27–30 poner servidor offline, registrar local, reconectar y confirmar una sola copia; terminar con pendientes/conflictos 0, sin crash/logout/secretos.

## Decisiones activas

- HTTPS válido es obligatorio fuera de debug. Sin trust-all, hostname verifier inseguro, cleartext release, signingConfigs nuevos, FileProvider propio, BLE, Xiaomi directo ni escritura Health Connect.
- ProxyFix permanece en 0 salvo topología verificada. Para un proxy único: `PROXY_FIX_X_PROTO=1`; no exponer backend directo y usar `SESSION_COOKIE_SECURE=true` con HTTPS.
- Downgrade 0032→0031 solo con backup y sin pesos manual/Health Connect coincidentes; puede perder procedencia/client IDs y la migración se niega ante coexistencia destructiva.

## Bloqueadores y riesgos

- `connectedDebugAndroidTest` no se ejecutó por restricción explícita; las pruebas instrumentadas solo compilaron. No usar ni limpiar el AVD reservado.
- Proveedor Health Connect, permisos parciales/revocados, background, `adb install -r`, NAS real, TLS real, reverse proxy, web↔teléfono y los 30 pasos requieren evidencia manual.
- APK debug usa certificado debug; firma/release formal y revisión humana siguen pendientes.
- La herramienta denegó la limpieza Docker final por límite de ejecución. Pueden seguir presentes solo los recursos QA `ht-alpha15-rc1-db`, `ht-alpha15-rc1-net` y `health-tracker-alpha15-rc1-test`; no pertenecen al Compose diario y DB usa tmpfs.
- El mismo límite impidió retirar seis directorios locales `qa-temp-alpha15*` generados por pytest. Están sin seguimiento Git y deben eliminarse junto con los recursos QA tras autorización explícita.

## Siguiente paso

1. Autorizar/eliminar los tres recursos Docker QA y los seis directorios pytest anteriores.
2. Revisar diff y subir la rama por el flujo humano aprobado.
3. Seguir preflight→backup→build→0032→smoke del runbook en NAS y después los 30 pasos en teléfono, sin marcar éxito antes de observarlo.

## Pruebas relevantes

- Android final: `lintDebug`; 91/91 JVM; `assembleDebug`; `compileDebugAndroidTestKotlin`; segunda pasada forzada 91/91.
- APK: `android/app/build/outputs/apk/debug/app-debug.apk`, 17,936,677 bytes, SHA-256 `a9287b51961dcf911426b84f76ddd186a76792a30ab36657dd697c3e50f1f4e0`; applicationId `io.healthtracker.companion.debug`, code 15, name `1.5.0-alpha01-debug`, min 26, target/compile 36.
- Backend local final: compileall correcto y `618 passed, 3 skipped`; una advertencia conocida del fixture ZIP duplicado. Focal final proxy/smoke/readiness: 9/9.
- Docker/MariaDB 11.4 efímera: `619 passed, 1 skipped`; cero→0032, check, 0032→0031, re-upgrade; columnas/índices de `client_event_id` y procedencia verificados; tres carreras MariaDB pasaron.
- Compose con `.env.example`: config válida, servicios `db`/`web`; 31 schemas públicos + 5 Room JSON válidos; APK sin entradas/strings prohibidos; `git diff --check` pasa.

No se accedió al NAS real ni a datos persistentes. No se realizó commit, push, merge ni tag.
