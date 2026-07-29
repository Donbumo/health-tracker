# Handoff activo

## Estado actual

- Rama: `feature/alpha-1.5-health-connect`. HEAD observado al iniciar esta tanda: `13c3e545d41c3e1d5a7412b2feeb6d16f963a6cb`; ese commit ya existía pese a que el encargo citaba `dab0bc3` y cambios sin commit. La tanda actual queda sin staging ni commit.
- Alpha 1.5 RC1 conserva applicationId release `io.healthtracker.companion`, debug `.debug`, versionCode 15, versionName `1.5.0-alpha01`, min SDK 26 y target/compile 36.
- Identidad de servidor canoniza esquema, host, puerto y base path; HTTPS `:443` y HTTP local `:80` equivalen al puerto implícito. Se rechazan control, userinfo, query, fragmento, puertos inválidos, separadores codificados, traversal, backslash, path ambiguo y HTTP público.
- OkHttp y el smoke no siguen redirecciones. Un host distinto o downgrade HTTPS→HTTP no recibe Authorization ni cuerpo.
- Tokens cifrados siguen ligados a la identidad normalizada. Una generación de mutación impide que un refresh tardío repueble credenciales tras logout o cambio de servidor. Un worker viejo no limpia una cuenta nueva.
- Un `401` sin código definitivo conserva la sesión local/offline. Solo refresh inválido confirmado, revocación o logout limpian credenciales.
- Health Connect sigue opt-in y opcional. Errores reintentables llegan a WorkManager; permisos revocados permanecen por tipo; tokens se avanzan tras persistencia. El diagnóstico trunca `last_import_at` a la hora.
- Room continúa en v5 sin fallback destructivo; 1/2/3/4→5 es explícito, 4→5 conserva pendientes, draft, plan, historial y salud, y v5 reabre conservando filas.
- El downgrade 0032 valida antes de cualquier DDL: rechaza client IDs, nutrición no manual o pesos coexistentes que perderían procedencia.

## Pruebas relevantes

- Android: `lintDebug`, dos `testDebugUnitTest --rerun-tasks`, `assembleDebug` y `compileDebugAndroidTestKotlin`, todos correctos. Las instrumentadas compilaron; no se ejecutó `connectedDebugAndroidTest`.
- Backend local: `620 passed, 3 skipped`; simulador integrado Alpha 1.5 incluido.
- MariaDB 11.4 efímera: build, readiness, cero→0032, `db check`, smoke read-only/write con cleanup y ciclo seguro 0031→0032→0031→0032 correctos. Suite Docker final: `621 passed, 1 skipped`.
- Todo laboratorio usó red y nombres exclusivos con `tmpfs`; tras cada intento quedaron 0 contenedores, 0 redes y 0 volúmenes nuevos.
- APK debug: `android/app/build/outputs/apk/debug/app-debug.apk`, 17,935,727 bytes, SHA-256 `1ca23b52cba26094564c8169e207c805965c56665854fd59b14840cf7e1dadf6`; firma v2 válida, code 15, name `1.5.0-alpha01-debug`, min 26, target/compile 36, debuggable y backups deshabilitados.
- Escaneo APK: sin `.env`, secretos de backend, Bearer literal, clave privada, IP de emulador, tokens ni `qa-temp-alpha15` detectados.

## Trabajo en curso

- `scripts/release/alpha15_phone_preflight.ps1`: selección segura de un dispositivo, serial enmascarado, propiedades, espacio, APK/firma/versiones y compatibilidad conservadora; nunca instala ni limpia.
- `scripts/release/alpha15_apk_manifest.ps1`: manifiesto local con hash, tamaño, package, versiones, SDK, fecha, commit y dirty/clean.
- `scripts/release/alpha15_postdeploy_readonly.sh`: estado Compose, Alembic, readiness, rutas públicas, logs acotados y smoke autenticado opcional sin escribir.
- `scripts/release/alpha15_smoke.py`: bloquea redirects, limita HTTP a hosts locales, limita cuerpos y mantiene write bajo confirmación explícita con cleanup.
- El runbook contiene bloques A–E para Windows, NAS predeploy/deploy, teléfono y rollback con placeholders.
- El mapa canónico de documentación continúa en `DOCUMENTATION_INDEX.md`.

## Bloqueadores y riesgos

- No se conectó al NAS ni a un teléfono. TLS y reverse proxy reales, `adb install -r`, proveedor Health Connect, permisos parciales/revocados, process death, offline y el recorrido manual de 30 pasos requieren evidencia mañana.
- El APK es debug; firma release formal sigue fuera de Alpha privada.
- `shellcheck` no está instalado; `bash -n`, parse PowerShell, ayudas y Python compile sí se validaron.
- Los seis `qa-temp-alpha15*` preexistentes permanecen intactos por instrucción explícita; no se cambiaron ACL ni se intentó borrarlos.
- Los servicios diarios no se reiniciaron ni modificaron. Verificar nuevamente IDs y `StartedAt` antes de la ventana humana.

## Siguiente paso

Revisar el diff humano, ejecutar el bloque A del runbook por el flujo aprobado y, solo después, seguir B→C→D. No declarar QA real hasta completar el teléfono y comprobar pendientes/conflictos 0, una sola copia de cada dato y ausencia de logout, crash y secretos.
