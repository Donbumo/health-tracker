# Handoff activo

## Beta 1 Android en esta rama

- Rama `beta/android-1.0-stabilization`; HEAD inicial `28299103477b22eac6f569153236fa426d2a0619`; freeze de Alpha 2.0 sin funciones nuevas y sin staging.
- Android pasa a code 21/name `2.0.0-beta01`; Room continúa 10, Alembic continúa 0036 y no cambian firma, applicationId, SDKs ni toolchain.
- Se corrigieron dos P1: cancelación absorbida por workers/colas y path traversal mediante IDs remotos en cachés médicas/de actividad. Un P2 corrige el mensaje UTF-8 de límite de exportación. Hay seis nuevas regresiones JVM.
- La matriz instrumentada declara por separado Room 1/2/3/4/5/6/7/8/9→10 y reapertura v10 con fixtures ficticias preservadas.
- Herramientas en `scripts/beta/` crean/validan/eliminan exclusivamente un AVD `health-tracker-beta1-qa-<id>`, fijan serial, auditan APK/MariaDB y escriben reportes bajo `%TEMP%`; su harness PowerShell 5.1 pasa 25 aserciones.
- Gates finales: backend local 716/9; Docker/MariaDB 724/1 con cero→0036 y dos ciclos 0036↔0035; 77 schemas correctos; Android `lintDebug`, 172/172 JVM, APK, 123 androidTest compilados y segunda JVM 172/172.
- APK Beta debug: 18.213.405 bytes, SHA-256 `3758030fa28acbe579b90fc6ddcbfaa5a8b2d60d53cb6ba64592917ac4ebf5f9`, code 21/name `2.0.0-beta01-debug`, firma v2, 173 entradas y escaneo sensible limpio.
- MariaDB usó contenedor/red exclusivos y tmpfs; contenedor, red, imagen y storage propios se eliminaron. Los dos volúmenes y ambos contenedores diarios quedaron intactos; Compose diario no se ejecutó.
- AVD e instrumentación están bloqueados honestamente: el SDK solo tiene una imagen API 37.1 Play Store y no tiene `avdmanager`; `Pixel_7` no se tocó. Upgrade, reboot, rendimiento medido, layouts y TalkBack permanecen pendientes.
- QA físico no se ejecutó. Seguir `BETA_1_PHYSICAL_QA_RUNBOOK.md`; no declarar release final.

## Estado actual

- Beta 1 está técnicamente estabilizada para iniciar QA físico controlado; no es release final.
- El mapa canónico de contexto permanece en `DOCUMENTATION_INDEX.md`; el detalle Beta está en `BETA_1_ANDROID_STABILIZATION.md` y `ANDROID_RELEASE_READINESS.md`.

## Pruebas relevantes

- Backend local 716/9; Docker/MariaDB 724/1; 77 schemas públicos válidos.
- Android: lint, dos JVM forzadas 172/172, APK y 123 tests instrumentados compilados.
- APK Beta: code 21/name `2.0.0-beta01-debug`, 18.213.405 bytes, firma v2 y escaneo sensible limpio.

## Trabajo en curso

- Sólo quedan revisión humana del diff y los gates conectados/manuales del runbook físico Beta 1.

## Bloqueadores y riesgos

- Falta una imagen Android instalada sin Play Store y falta `avdmanager`; no se creó AVD ni se seleccionó serial.
- Instrumentación, `adb install -r`, process death/reboot, rendimiento medido, layouts y TalkBack siguen pendientes.
- Los directorios inaccesibles `qa-temp-alpha15*` son preexistentes y deben permanecer intactos.

## Siguiente paso

Revisar el diff sin añadirlo al staging e instalar, fuera de esta tanda, cmdline-tools y una imagen API 35/36 no-Play para ejecutar `BETA_1_PHYSICAL_QA_RUNBOOK.md` en un recurso autorizado.
