# Handoff activo

## Estado actual

- Rama actual: `feature/alpha-1.5-phone-qa-tooling`. HEAD inicial y final esperado: `1c3d7c3642295964e6417ee1592a4046e6567835`, Alpha 1.5 RC1. La tanda de tooling queda sin staging ni commit.
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
- Tooling de teléfono: parser de ocho scripts, seis ayudas y harness PowerShell 5.1 con 42/42 casos ficticios correctos; cleanup temporal completo. El diagnóstico Health Connect focal deja 93/93 JVM en ambas pasadas.
- SDK real: resolución automática encontró adb 1.0.41 y build-tools estable 36.0.0 con aapt/apksigner. El APK RC1 externo validó package, code/name, SDKs, debug, firma, 17.293.357 bytes y SHA-256 `6e3ce9bb77c28d04f2a0eae8b7c647ff876d15d959a06fbd6aed6f20f32d34c4`. Sin teléfono conectado, preflight terminó limpiamente con código lógico 5 `device_missing` después de validar toolchain/APK.
- Backend local: `620 passed, 3 skipped`; simulador integrado Alpha 1.5 incluido.
- MariaDB 11.4 efímera: build, readiness, cero→0032, `db check`, smoke read-only/write con cleanup y ciclo seguro 0031→0032→0031→0032 correctos. Suite Docker final: `621 passed, 1 skipped`.
- Todo laboratorio usó red y nombres exclusivos con `tmpfs`; tras cada intento quedaron 0 contenedores, 0 redes y 0 volúmenes nuevos.
- APK debug: `android/app/build/outputs/apk/debug/app-debug.apk`, 17,935,727 bytes, SHA-256 `1ca23b52cba26094564c8169e207c805965c56665854fd59b14840cf7e1dadf6`; firma v2 válida, code 15, name `1.5.0-alpha01-debug`, min 26, target/compile 36, debuggable y backups deshabilitados.
- Escaneo APK: sin `.env`, secretos de backend, Bearer literal, clave privada, IP de emulador, tokens ni `qa-temp-alpha15` detectados.

## Trabajo en curso

- `scripts/release/alpha15_phone_common.ps1`: resolución SDK/toolchain, inspección APK, selección de dispositivo, package/certificado instalado y cleanup temporal reutilizables.
- `scripts/release/alpha15_phone_preflight.ps1`: preflight read-only con salida/exit codes estructurados; valida firma instalada antes de recomendar actualización.
- `scripts/release/alpha15_phone_install.ps1`: ejecuta preflight y solo permite `adb install -r` con confirmación literal; después verifica package, versión y certificado.
- `scripts/release/alpha15_phone_smoke.ps1` y `alpha15_phone_logs.ps1`: launch/restart/logs solo por switches explícitos; hallazgos redactados y ventana acotada.
- `scripts/release/alpha15_phone_qa.ps1`: sesiones coordinadas fuera del repositorio con doble confirmación para `-All` y checklist manual de 28 puntos.
- `scripts/release/alpha15_apk_manifest.ps1`: manifiesto temporal estricto RC1 con hash, tamaño, package, versiones, SDK, certificado corto, branch, commit y dirty/clean.
- `scripts/release/alpha15_postdeploy_readonly.sh`: estado Compose, Alembic, readiness, rutas públicas, logs acotados y smoke autenticado opcional sin escribir.
- `scripts/release/alpha15_smoke.py`: bloquea redirects, limita HTTP a hosts locales, limita cuerpos y mantiene write bajo confirmación explícita con cleanup.
- El NAS conserva su runbook; [ALPHA_1_5_PHONE_QA_RUNBOOK.md](ALPHA_1_5_PHONE_QA_RUNBOOK.md) concentra USB, preflight, firma, instalación, smoke, Health Connect, logs, conservación y rollback del teléfono.
- El mapa canónico de documentación continúa en `DOCUMENTATION_INDEX.md`.

## Bloqueadores y riesgos

- No se conectó al NAS ni había teléfono visible para adb. No se instaló, lanzó, reinició ni limpió nada. Firma instalada, `adb install -r`, proveedor Health Connect, permisos parciales/revocados, process death, offline y recorrido manual requieren evidencia física.
- El APK es debug; firma release formal sigue fuera de Alpha privada.
- `shellcheck` no está instalado; `bash -n`, parse PowerShell, ayudas y Python compile sí se validaron.
- Los seis `qa-temp-alpha15*` preexistentes permanecen intactos por instrucción explícita; no se cambiaron ACL ni se intentó borrarlos.
- Los servicios diarios no se reiniciaron ni modificaron. Verificar nuevamente IDs y `StartedAt` antes de la ventana humana.

## Siguiente paso

Revisar el diff humano y seguir [ALPHA_1_5_PHONE_QA_RUNBOOK.md](ALPHA_1_5_PHONE_QA_RUNBOOK.md): primero preflight read-only; después decidir por separado instalación y QA. No declarar preservación ni QA real hasta comprobar en teléfono pendientes/conflictos 0, una sola copia de cada dato y ausencia de pérdida, logout, crash y secretos.
