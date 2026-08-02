# Android release readiness — Beta 1

Estado técnico de `2.0.0-beta01-debug` después del cierre conectado del 1 de agosto de 2026.

| Gate | Estado | Evidencia o límite |
| --- | --- | --- |
| Freeze funcional | Aprobado | Sin funciones nuevas ni Alpha 2.1. |
| Android local | Aprobado | Lint; JVM 172/172 dos veces; assemble; androidTest compile. |
| Harness Beta | Aprobado | 60/60 aserciones en PowerShell 5.1. |
| Imagen/AVD | Aprobado y limpiado | API 36 `google_apis` x86_64 no-Play; AVD exclusivo, identidad validada y eliminación obligatoria. |
| Instrumentación | Aprobado | 123 fuente/123 ejecutados/123 aprobados; 0 omitidos y 0 fallidos en 22 clases. |
| Room 1→10/reapertura | Aprobado | Rutas 1/2/3/4/5/6/7/8/9→10 y reapertura v10 ejecutadas; cero fallback destructivo. |
| Upgrade `adb install -r` | Aprobado | Code 19/Room 9→code 21/Room 10, misma firma, DataStore/Keystore/Room/draft/pendiente/archivo preservados y cero duplicados. |
| Modo avión/process death | Aprobado con límites | Modo avión, force-stop y reapertura reales; persistencia verificada. El recorrido UI completo contra backend fake hasta cola cero sigue pendiente. |
| WorkManager/reboot | Aprobado con límites | Jobs reales y reboot observados; batería/restricciones OEM pendientes. |
| Notificaciones | Aprobado con límites | Permiso denegado/concedido y cuatro canales reales; políticas JVM verdes. Snooze/dismiss/ack manuales pendientes. |
| SAF/FileProvider | Aprobado automatizado | Suite instrumentada verde; chooser/grants/URI perdida y matriz de archivos manuales pendientes. |
| Rendimiento | Aprobado parcial | Dataset Room 38.500 filas, consultas 0–20 ms, PSS y DB medidos; series densas, límites portables y pantallas completas pendientes. |
| Layout automatizado | Aprobado parcial | Diez configuraciones, cero overflow/targets pequeños en la pantalla alcanzable; matriz completa pendiente. |
| TalkBack | Pendiente | Requiere recorrido manual; no está aprobado. |
| Health Connect/OEM/teléfono | Pendiente | Requiere QA físico autorizado. |
| Seguridad/APK | Aprobado | 18.886.619 bytes; 173 entradas; firma v2; 19 permisos; cero hallazgos sensibles bloqueantes. |
| Backend/MariaDB/schemas | Evidencia conservada | Sin cambios del área: backend 716/9, MariaDB efímera 724/1, Alembic 0036 y 77 schemas válidos. |

## Criterio de promoción

Los gates Android conectados automatizables quedan cerrados y Beta 1 puede pasar a QA físico controlado. No debe declararse release final hasta completar TalkBack, la matriz física/OEM, Health Connect real, SAF interactivo y el recorrido completo offline→autosync contra un backend fake.
