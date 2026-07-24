# Instalación local Android

Requisitos ya instalados: JDK 17, Android SDK Platform 36, Build Tools 35+ y platform-tools. No aceptes licencias automáticamente en una máquina ajena.

```powershell
Set-Location android
.\gradlew.bat assembleDebug
adb devices
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
```

Al abrir:

1. Escribe la URL raíz del servidor.
2. Usa HTTPS en LAN/VPN. Para emulador debug contra el host, puede usarse `http://10.0.2.2:<puerto>` tras activar la confirmación de HTTP local.
3. Prueba la conexión.
4. Inicia sesión; el login registra el UUID estable de esta instalación.

Release no incorpora URL ni firma privada. Para un APK release local configura un keystore fuera del repositorio; nunca añadas `.jks`, `.keystore` o `signing.properties` a Git.
