# Health Tracker Android Companion

Aplicación Android nativa de Alpha 1.1 para ejecutar entrenamientos cotidianos con cache local y sincronización al recuperar red. Reutiliza API Auth, Mobile Sync 1.0 y Companion Delivery 1.0; no contiene un backend alternativo.

## Stack fijado

- AGP 8.13.2, Gradle 8.13 y JDK 17.
- Kotlin 2.3.21 y kotlinx.coroutines 1.11.0.
- `compileSdk`/`targetSdk` 36; `minSdk` 26.
- Compose BOM 2026.06.00, Material 3 y Navigation Compose.
- Room 2.8.4, DataStore 1.2.1 y WorkManager 2.11.2.
- OkHttp 5.4.0 y kotlinx.serialization 1.11.0.

Se eligió un solo módulo `app` con paquetes `core` y `ui`: la alfa necesita fronteras lógicas claras, no el coste de muchos módulos Gradle. Las versiones son estables, soportan API 36 y evitan la migración disruptiva a Kotlin integrado de AGP 9 durante este primer cliente.

## Construcción

Requiere JDK 17 y Android SDK 36/Build Tools 35 o posterior ya instalados. El repositorio no instala herramientas ni acepta licencias automáticamente.

```powershell
Set-Location android
.\gradlew.bat --version
.\gradlew.bat lintDebug
.\gradlew.bat testDebugUnitTest
.\gradlew.bat assembleDebug
```

Con dispositivo/emulador:

```powershell
.\gradlew.bat connectedDebugAndroidTest
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
```

`debug` permite HTTP únicamente tras confirmación en la app y validación de loopback, `10.0.2.2`, RFC1918 o `.local`. `release` rechaza cleartext. No se versionan `local.properties`, keystores ni artefactos `build/`.

Consulta [instalación](../docs/ANDROID_INSTALLATION.md), [seguridad](../docs/ANDROID_SECURITY.md), [sync offline](../docs/ANDROID_OFFLINE_SYNC.md) y [pruebas](../docs/ANDROID_TESTING.md).
