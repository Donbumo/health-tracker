# Alpha 1.5 RC1: instalación y QA conservador en teléfono

Este runbook prepara y registra una actualización de `io.healthtracker.companion.debug` sin asumir que el teléfono, la firma o los datos ya son compatibles. Los comandos son seguros por defecto; instalar, iniciar, reiniciar o limpiar logcat exige una opción explícita. Usa únicamente una cuenta y datos ficticios.

## Límites

- No uses `adb uninstall`, `pm clear`, `install -d`, `run-as`, `adb root`, backups de datos ni pulls de bases, preferencias, Room o Keystore.
- No cambies Wi-Fi, datos, modo avión, permisos ni Health Connect mediante scripts.
- No instales hasta revisar el preflight y confirmar literalmente `ALPHA15-INSTALL`.
- Una firma distinta o un downgrade detienen el proceso. Desinstalar no es el primer paso: borraría los datos de la aplicación.
- `adb install -r` pretende conservar el package data, pero la preservación solo se aprueba después del checklist físico pre/post.

## Requisitos

- Windows PowerShell 5.1 o posterior.
- Android SDK instalado; no es necesario que sus herramientas estén en `PATH`.
- APK RC1 debug esperado: package `io.healthtracker.companion.debug`, `versionCode=15`, `versionName=1.5.0-alpha01-debug`.
- Cable USB confiable, depuración USB activada y autorización humana visible en el teléfono.
- APK y teléfono bajo control del operador; no compartas serial, rutas del perfil ni logs crudos.

## Descubrimiento automático del SDK

La biblioteca `scripts/release/alpha15_phone_common.ps1` busca en este orden:

1. `-AndroidSdkRoot`, `-AdbPath`, `-AaptPath`, `-ApksignerPath`.
2. `PATH`, aceptando únicamente herramientas que pertenezcan al SDK resuelto.
3. `ANDROID_SDK_ROOT`.
4. `ANDROID_HOME`.
5. `android/local.properties` (`sdk.dir`).
6. `%LOCALAPPDATA%\Android\Sdk`.
7. `%ProgramFiles%\Android\Sdk` cuando exista.

`adb` se toma de `platform-tools`. `aapt.exe` o `aapt2.exe` y `apksigner.bat/.exe` se toman de la versión estable semánticamente más alta de `build-tools` que contenga las herramientas necesarias. Una preview requiere `-AllowPreviewBuildTools` o una ruta explícita.

## 1. Preflight read-only

Conecta el teléfono, acepta manualmente el diálogo de depuración USB y ejecuta:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\release\alpha15_phone_preflight.ps1 `
  -ApkPath 'C:\tmp\health-tracker-releases\alpha-1.5-rc1\health-tracker-alpha-1.5-rc1-debug.apk' `
  -Json
```

Si hay más de un dispositivo, vuelve a ejecutar con `-Serial '<serial-exacto>'`. El serial se usa internamente para seleccionar, pero el reporte normal conserva solo un fingerprint corto. `-ShowSensitiveIdentifiers` es únicamente para diagnóstico local y no debe usarse en reportes compartibles.

El preflight valida, antes de cualquier consulta al teléfono, SDK, versiones de herramientas, tamaño/hash/firma del APK, package, versión, SDKs, debuggable y certificado. Después valida estado `device`, autorización, boot, API, ABI, espacio, batería opcional, package instalado, versión y certificado recuperando temporalmente solo su APK base. La copia temporal siempre se elimina.

| Exit | Significado |
| ---: | --- |
| 0 | Listo para considerar instalación manual confirmada |
| 2 | Argumentos inválidos |
| 3 | SDK/toolchain incompleto |
| 4 | APK inválido o no es RC1 Alpha 1.5 |
| 5 | Dispositivo ausente, múltiple, offline, recovery/bootloader o incompatible |
| 6 | Firma distinta o imposible de verificar |
| 7 | Candidate `versionCode` menor |
| 8 | Espacio insuficiente o no verificable |
| 9 | Dispositivo no autorizado |
| 10 | Error inesperado sanitizado |

Estados de comparación: `package_not_installed`, `candidate_newer`, `same_version`, `candidate_older`, `signature_mismatch` y `unable_to_verify`. `compatible_upgrade` solo significa que el certificado coincide; no aprueba por sí solo el QA.

## 2. Manifiesto compartible del APK

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\release\alpha15_apk_manifest.ps1 `
  -ApkPath 'C:\tmp\health-tracker-releases\alpha-1.5-rc1\health-tracker-alpha-1.5-rc1-debug.apk'
```

Sin `-OutputPath`, el JSON queda en un directorio único bajo `%TEMP%`, no dentro de `android/app/build`. Incluye hash, tamaño, package/versiones/SDKs, debug, certificado corto, branch, commit y dirty/clean. `-AllowDifferentAlphaVersion` es para reutilización general y no aprueba RC1.

## 3. Instalación confirmada

Revisa el preflight. Después, y solo si firma, versión, API, estado y espacio son compatibles:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\release\alpha15_phone_install.ps1 `
  -ApkPath 'C:\tmp\health-tracker-releases\alpha-1.5-rc1\health-tracker-alpha-1.5-rc1-debug.apk' `
  -ConfirmInstall 'ALPHA15-INSTALL' `
  -OutputPath (Join-Path $env:TEMP 'alpha15-install.json')
```

El único comando de instalación es `adb install -r <apk>`. No se usa `-d`, `-t`, uninstall, `pm clear` ni grant-all. Tras éxito se vuelven a comprobar package, versionCode, versionName y certificado. `-Launch` inicia la launcher activity una sola vez; no pulsa ni rellena UI.

Ante error no hay retry en bucle ni desinstalación. Conserva `preflight.json`/`install.json`, detente y revisa la causa.

## 4. Smoke explícito

Inspección de package y proceso, sin lanzar:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\release\alpha15_phone_smoke.ps1 -Json
```

Operaciones opcionales independientes:

```powershell
# Iniciar una vez
.\scripts\release\alpha15_phone_smoke.ps1 -Launch -Json

# force-stop y reabrir sin borrar datos
.\scripts\release\alpha15_phone_smoke.ps1 -Restart -Json

# Solo ventana acotada y hallazgos sanitizados
.\scripts\release\alpha15_phone_smoke.ps1 -CollectLogs -LastLogLines 500 -Json
```

`-ClearLogcat` es explícito y no forma parte del flujo normal. Un log crudo requiere `-RawLogOutputPath` fuera del repositorio y contiene una advertencia; elimínalo tras revisión.

Resultados: `package_missing`, `launch_failed`, `process_started`, `restart_survived`, `crash_detected`, `anr_detected`, `sensitive_log_candidate` o `clean_basic_smoke`.

## 5. Sesión coordinada

El orquestador crea `%TEMP%\health-tracker-alpha15-qa\<session-id>` y, según el modo, solamente estos artefactos: `preflight.json`, `install.json`, `smoke.json`, `package-before.json`, `package-after.json`, `sanitized-log-findings.json`, `qa-checklist.md` y `summary.json`.

```powershell
# Predeterminado: preflight
.\scripts\release\alpha15_phone_qa.ps1 -ApkPath '<APK>'

# Reporte/checklist sin teléfono
.\scripts\release\alpha15_phone_qa.ps1 -Report

# Flujo completo, solamente tras dos decisiones humanas separadas
.\scripts\release\alpha15_phone_qa.ps1 -ApkPath '<APK>' -All `
  -ConfirmInstall 'ALPHA15-INSTALL' -ConfirmQa 'ALPHA15-QA'
```

`-All` no automatiza login ni el recorrido funcional. Las confirmaciones autorizan únicamente install/launch/restart/logs acotados definidos por los scripts.

## 6. Conservación pre/post

Antes y después se comparan package, versión y tiempos reportados por package manager, sin abrir el directorio privado. Confirma manualmente en `qa-checklist.md`:

- login y servidor;
- Room, historial y health cache/ledger;
- DataStore/preferencias y Keystore;
- draft activo, planes y operaciones pendientes;
- ausencia de duplicados, logout inesperado y pérdida de datos.

No marques preservación como aprobada basándote solo en `adb install -r` o en timestamps.

## 7. Health Connect

No leas Health Connect con adb. En la aplicación abre Ajustes → Health Connect y comparte el diagnóstico sanitizado. Debe contener versión de app/Android, estado y disponibilidad del proveedor, necesidad de actualización, conteo/grupos genéricos seleccionados y concedidos, última importación truncada, pendientes, último código de error y estado de background.

No debe contener valores, IDs, origins completos, changes token, tokens, headers ni nombres concretos de métricas. Recorre manualmente proveedor ausente/actualizable, permisos parciales, revocación parcial, foreground/background, offline/reconexión y pendientes finales en cero.

## 8. Logs

El reporte normal guarda solo patrón, categoría, minuto truncado, origen, clasificación y `[REDACTED]`. Las clases son `real_candidate`, `generic_identifier`, `test_fixture` y `unknown`. Revisa crash/ANR, Room/migraciones, red y Health Connect; una coincidencia secreta real o desconocida bloquea la aprobación.

## 9. Errores frecuentes

- **adb no encontrado:** comprueba `platform-tools` o pasa `-AndroidSdkRoot`/`-AdbPath`.
- **aapt/apksigner no encontrados:** comprueba `build-tools`; `apksigner.bat` es válido. No copies binarios al repositorio.
- **unauthorized:** desbloquea el teléfono y acepta la clave RSA; vuelve a ejecutar preflight.
- **múltiples dispositivos:** usa `-Serial` exacto; el reporte seguirá mostrando fingerprint.
- **device offline/recovery/bootloader:** recupera manualmente el estado normal; no fuerces acciones desde el script.
- **`INSTALL_FAILED_UPDATE_INCOMPATIBLE`:** conserva evidencia; no desinstales. Verifica package y certificado.
- **`INSTALL_FAILED_VERSION_DOWNGRADE`:** no uses `-d`; produce un candidato aprobado con versionCode válido.
- **espacio insuficiente:** libera espacio manualmente sin borrar datos de Health Tracker y repite preflight.
- **Health Connect ausente/parcial:** usa la UI del sistema y la app; no concedas/revoques por adb.

## 10. Rollback del APK

Un APK anterior suele tener versionCode menor, por lo que este kit lo bloquea. No uses `install -d` ni desinstales: ambas rutas pueden romper la evidencia y la segunda borra datos. La recuperación conservadora requiere decidir entre restaurar el teléfono desde un procedimiento aprobado o producir un APK firmado con el mismo certificado y un versionCode superior. Conserva los reportes y escala la decisión de release.

## Checklist funcional manual

El archivo generado contiene 28 casillas: login, cold start, Hoy, entrenamiento descargado, start offline, autosave, process death, continue, complete, autosync, Plan, Programación, Historial, Progreso, peso, nutrición, pasos, Health Connect, permisos/revocación parcial, servidor offline/reconexión, pendientes/conflictos cero, sin duplicados/crash/logout inesperado/secretos.

Compilación, harness y fakes no aprueban este recorrido. Tampoco se ejecuta `connectedDebugAndroidTest` sobre el teléfono QA.
