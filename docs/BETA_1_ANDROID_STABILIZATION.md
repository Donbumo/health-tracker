# Beta 1 — estabilización Android 2.0

## Alcance y baseline

Beta 1 congela las capacidades de Alpha 2.0. No añade dominios, métricas ni funciones de producto y no abre Alpha 2.1.

- Rama observada durante toda la tanda: `beta/android-1.0-stabilization`.
- HEAD inicial y final: `1093d4d14c7aa52f180ed7d1ba17cea5437dc896`.
- El árbol y staging comenzaron limpios; los cambios de esta tanda quedan solo en el working tree.
- Versiones conservadas: code 21, `2.0.0-beta01` (`2.0.0-beta01-debug`), Room 10 y Alembic `20260731_0036`.
- No cambiaron `applicationId`, firma, SDKs, toolchain ni schemas públicos.
- No se leyó `.env`, no se usaron `/data`, NAS, Compose/MariaDB diarios, teléfono físico, `Pixel_7` ni `qa-temp-alpha15*`.

## Imagen y AVD desechable

El nuevo Android CLI se intentó primero para instalar `system-images;android-36;google_apis;x86_64`, pero terminó con error nativo `-1073740791` durante la descarga. El fallback exacto con `sdkmanager.bat` terminó correctamente. Se verificaron `package.xml`/`source.properties`, API 36, tag `google_apis`, ABI `x86_64` y ausencia de Play Store. La imagen, de 4,27 GiB, se conserva instalada conforme al encargo.

Se creó únicamente `health-tracker-beta1-qa-qa-a5cd1219035b`, con cold boot, sin snapshot ni cuenta Google. El runner validó nombre, configuración, system image, API, ABI, serial de emulador y ausencia de cualquier otro dispositivo antes y después de ejecutar comandos. El fingerprint sanitizado del serial es `04ab3fc3`; el serial completo no se publica. `Pixel_7` permaneció apagado e intacto. El AVD y su perfil se eliminan durante el cierre obligatorio.

## Hallazgos y correcciones

| ID | Severidad | Evidencia y causa | Corrección y regresión |
| --- | --- | --- | --- |
| B1-P1-003 | P1 | Un refresh token recién escrito podía perderse si el proceso era terminado inmediatamente porque `SharedPreferences.apply()` es asíncrono. Se reprodujo en el upgrade real mediante force-stop. | Las mutaciones críticas de `SecureTokenStore` usan `commit=true`; `SecureTokenStoreTest` comprueba además que el XML persistido contiene el cifrado. |
| B1-P1-004 | P1 QA | Los schemas Room 1–10 no estaban empaquetados en assets de `androidTest`, por lo que las migraciones conectadas no podían ejecutarse. | `androidTest` incorpora `app/schemas`; la suite conectada ejecutó todas las rutas y reapertura. |
| B1-P2-002 | P2 QA | Varias pruebas MockWebServer bloqueaban el hilo que debía atender el servidor y fixtures antiguas ya no representaban la identidad de servidor/schema vigentes. | Esperas acotadas en `Dispatchers.IO`, tokens ligados al servidor y fixtures Room/DAO actualizadas; suite completa repetida. |
| B1-P2-003 | P2 | Una `ZipException` de ruta insegura podía escapar del clasificador portable como error no normalizado. | Se transforma en `unsafe_path` o `invalid_archive` sin exponer el path. |
| B1-P2-004 | P2 QA | Scheduling y refresh suplementario hacían no deterministas pruebas de persistencia/sync. | Inyección con defaults productivos y no-op exclusivamente en tests; cobertura conectada repetida. |

Se conservan los defectos ya corregidos en el checkpoint Beta: propagación de cancelación estructurada, nombres privados SHA-256 para archivos remotos y texto UTF-8 de límite de exportación. No se encontró un P0 reproducible.

## Gates Android finales

- `lintDebug`: aprobado, 62,282 s.
- Primera JVM forzada: 172/172 aprobados, 0 omitidos, 0 fallidos, 41,066 s.
- `assembleDebug`: aprobado, 2,444 s.
- `compileDebugAndroidTestKotlin`: aprobado, 1,319 s.
- Segunda JVM forzada: 172/172 aprobados, 0 omitidos, 0 fallidos, 32,587 s.
- Harness PowerShell 5.1: 60/60 aserciones.
- Instrumentación final: 123 métodos fuente en 22 clases; 123 ejecutados, 123 aprobados, 0 omitidos, 0 fallidos, 33,151 s, sobre API 36.

Los únicos warnings relevantes fueron la opción kapt de schemas Room y APIs de Compose Test deprecadas; no hubo fallos. Backend, MariaDB y schemas públicos no se repitieron porque ningún cambio de esta tanda toca esos dominios; se conserva la evidencia del checkpoint: backend 716/9, MariaDB efímera 724/1 y 77 schemas válidos.

## Room y upgrade conservador

`CompanionActivityMigrationTest` ejecutó físicamente 1→10, 2→10, 3→10, 4→10, 5→10, 6→10, 7→10, 8→10, 9→10 y reapertura v10. También pasaron las migraciones específicas de los dominios incorporados en versiones intermedias. No existe `fallbackToDestructiveMigration`.

El upgrade partió del commit reproducible `350cf2ced53bc2ba6a7c18421780ce8045b8c07f` (code 19, `1.9.0-alpha01-debug`, Room 9), construido en un worktree temporal externo. Su APK SHA-256 fue `667a725a7905fca37a54fcd876ca674e6e2400aaba7b98d95881b76e99822b2e` y usó el mismo certificado debug SHA-256 que Beta: `d89829d191d2783cfc280787781e0847ec3d4184eb4fa98981449849dd089a46`.

Sin uninstall, `pm clear` ni `-d`, `adb install -r` conservó una cuenta, delivery, package, draft, acción pendiente, preferencias DataStore, refresh token cifrado en Keystore y archivo marcador ficticios. La verificación posterior confirmó Room 10, code 21, un solo registro de cada fixture y cero duplicados o logout por corrupción.

## Recorridos conectados y límites

- Offline/process death: se activó realmente modo avión solo en el AVD, se verificó el proceso detenido y la app reabrió offline; después se restauró conectividad. El upgrade verificó también force-stop/reapertura con sesión, draft y pendiente durables. La suite MockWebServer/Room cubre cola, reconnect, autosync, 200 y 409. No se ejecutó un backend fake completo después del modo avión, por lo que no se afirma el recorrido UI entero hasta pendientes cero.
- WorkManager/reboot: `dumpsys` confirmó jobs reales, incluidos constraint de red y programación temporal. Se reinició el mismo AVD y se verificaron boot, package manager, storage, launcher y reapertura. Los tests cubren unique work, cancelación, dedupe y políticas; no se afirma una matriz OEM de batería.
- Notificaciones: se observaron permiso denegado y concedido y cuatro canales (`attention_required_v1`, `daily_health_v1`, `summaries_v1`, `workouts_v1`). JVM cubre quiet hours, dedupe, antispam, contenido genérico y resumen semanal. Snooze/dismiss/acknowledge no se recorrieron manualmente de extremo a extremo.
- SAF/FileProvider: la suite instrumentada valida providers, URI/aislamiento y paquetes/archivos sintéticos. No se operó manualmente el chooser, grants persistibles/revocación ni todas las variantes PDF/JPEG/PNG/FIT/GPX/TCX/BLE; permanecen para QA físico.

## Rendimiento y layouts

Un test temporal sobre Room 10 insertó 1.000 sesiones, 5.000 body stats, 10.000 entradas nutricionales, 20.000 pasos, 1.000 goals, 500 estudios y 1.000 actividades. Consultas observadas: sesiones 1 ms, body 3 ms, nutrición 9 ms, pasos 20 ms, goals 2 ms, medical 0 ms y activities 2 ms; primera página de historial 0 ms, página por offset 0 ms y página nutricional diaria 2 ms. PSS pasó aproximadamente de 130.702 KiB a 135.766 KiB; la DB midió 9.637.888 bytes y fue eliminada. No se midieron series densas, paquetes cercanos al límite, apertura de todas las pantallas ni downsampling.

La matriz automatizada ejecutó diez configuraciones con 320/360/411/600 dp, portrait/landscape, font scale 1,0/1,3/2,0 y temas claro/oscuro/sistema. Todos los lanzamientos accesibles pasaron con cero nodos fuera del viewport y cero targets pequeños detectados; los ajustes se restauraron en `finally`. La inspección se limitó a la pantalla alcanzable desde el estado sintético y no cubre todas las pantallas críticas. TalkBack permanece pendiente.

## APK y salida

La APK final `io.healthtracker.companion.debug` tiene code 21, name `2.0.0-beta01-debug`, minSdk 26, targetSdk 36, tamaño 18.886.619 bytes y SHA-256 `40eafddc91bc6f83ab53aed17b87df6d3dc2bf176ef5b05ffa563f6b18751d58`. Está firmada v2 con el certificado debug esperado; contiene 173 entradas y 19 permisos resultantes. El escaneo de secretos tuvo cero hallazgos bloqueantes.

Beta 1 queda lista para QA físico controlado, no como release final. Permanecen pendientes TalkBack, teléfono físico/OEM, Health Connect real, SAF/chooser manual, la matriz visual completa y el recorrido UI completo offline→backend fake→pendientes cero.
