# Handoff activo

## Beta 1 Android en esta rama

- Rama `beta/android-1.0-stabilization`; HEAD inicial/final `1093d4d14c7aa52f180ed7d1ba17cea5437dc896`; freeze de Alpha 2.0 sin funciones nuevas.
- Android conserva code 21/name `2.0.0-beta01`, Room 10, Alembic 0036, applicationId, firma, SDKs y toolchain.
- La imagen autorizada API 36 `google_apis` x86_64 se instaló con `sdkmanager.bat` después de que el nuevo Android CLI fallara nativamente. La imagen no-Play se conserva.
- Se usó únicamente el AVD desechable `health-tracker-beta1-qa-qa-a5cd1219035b`; fingerprint sanitizado `04ab3fc3`. No se usaron teléfono físico ni `Pixel_7`.
- Gates finales: lint; JVM 172/172 dos veces; APK; androidTest compile; harness 60/60; instrumentación 123/123 en 22 clases, cero skips/fallos.
- Room ejecutó 1/2/3/4/5/6/7/8/9→10 y reapertura v10, sin fallback destructivo.
- Upgrade real: APK reproducible code 19/Room 9 del commit `350cf2ced53bc2ba6a7c18421780ce8045b8c07f` a code 21/Room 10 con `adb install -r`, misma firma y sin uninstall/clear. Se preservaron Room, DataStore, Keystore, draft, pendiente y archivo marcador ficticios, sin duplicados.
- Se corrigió la ventana de pérdida del refresh token tras force-stop usando persistencia síncrona para las mutaciones críticas. También se corrigieron packaging de schemas Room, deadlocks/fixtures de instrumentación, clasificación de ZIP inseguro y aislamiento de scheduling en tests.
- Se ejecutaron modo avión y reapertura, reboot, estados denegado/concedido de notificaciones, canales y WorkManager real. La suite automatizada cubre sync/cola/dedupe; el recorrido UI completo contra backend fake hasta pendientes cero sigue pendiente.
- Rendimiento medido con 38.500 filas Room sintéticas: consultas observadas 0–20 ms, PSS 130.702→135.766 KiB y DB 9.637.888 bytes. Series densas, paquetes al límite y pantallas completas siguen sin medir.
- Layouts: diez configuraciones 320/360/411/600 dp, portrait/landscape, fuentes 1,0/1,3/2,0 y temas claro/oscuro/sistema; cero overflow/targets pequeños en la pantalla alcanzable. No equivale a la matriz completa ni a TalkBack.
- APK final: 18.886.619 bytes, SHA-256 `40eafddc91bc6f83ab53aed17b87df6d3dc2bf176ef5b05ffa563f6b18751d58`, firma v2, 173 entradas, 19 permisos y cero hallazgos sensibles bloqueantes.
- Backend/MariaDB/schemas no cambiaron; se conserva evidencia del checkpoint: 716/9, 724/1 y 77 schemas válidos.

## Estado actual

Los gates Android conectados automatizables están cerrados. El AVD, worktree, APKs y fixtures temporales propios se eliminan en el cierre y los reportes finales quedan fuera del repositorio. Compose diario, volúmenes, `.env`, `/data`, NAS y `qa-temp-alpha15*` permanecen intactos.

## Trabajo pendiente

- QA físico autorizado y restricciones OEM/batería.
- TalkBack manual y matriz visual de todas las pantallas críticas.
- Health Connect real.
- SAF/chooser, grants, URI perdida y variantes de archivos recorridos manualmente.
- Recorrido UI completo modo avión→process death→reconexión→autosync contra backend fake hasta pendientes cero.
- Snooze/dismiss/acknowledge de notificaciones de extremo a extremo.

## Siguiente paso

Revisar el working-tree diff sin añadirlo al staging y ejecutar `BETA_1_PHYSICAL_QA_RUNBOOK.md` en un recurso físico explícitamente autorizado. Beta 1 está lista para ese QA controlado; no es una release final.
