# Android release readiness — Beta 1

Estado de salida técnica para `2.0.0-beta01-debug`. “Compilado” no significa “ejecutado en dispositivo”.

| Gate | Estado | Evidencia o bloqueo |
| --- | --- | --- |
| Freeze funcional | Aprobado | Sin módulos/capacidades nuevas. |
| P0/P1 local | Aprobado con límites | Cero P0 reproducibles; dos P1 corregidos con regresión. |
| Backend local | Aprobado | 716 passed, 9 skipped. |
| Schemas | Aprobado | 77 Draft 2020-12 y refs locales. |
| Android lint/JVM/build/androidTest compile | Aprobado | `lintDebug`; 172/172 JVM; `assembleDebug`; 123 androidTest compilados; segunda JVM 172/172. |
| Room schemas | Aprobado estáticamente | Versiones 1–10 presentes; Room permanece 10. |
| Room 1→10 ejecutado | Bloqueado | No hay imagen instalada sin Play Store ni `avdmanager`. |
| AVD desechable | Bloqueado | Única imagen instalada: API 37.1 Play Store; `Pixel_7` protegido. |
| Instrumentación | Bloqueado | Cero tests conectados ejecutados. |
| Upgrade `adb install -r` | Bloqueado | Requiere AVD permitido y APK anterior reproducible con misma firma. |
| Offline/process death/WorkManager/reboot | Bloqueado en dispositivo | Cobertura JVM/androidTest compilable; recorrido real pendiente. |
| SAF/FileProvider/notificaciones | Bloqueado en dispositivo | Auditoría estática completa; interacción real pendiente. |
| Rendimiento Android medido | Bloqueado | No publicar métricas sin AVD. |
| Accesibilidad automatizada/layout | Bloqueado | Compilación disponible; configuraciones y TalkBack pendientes. |
| Seguridad manifest/red/archivos | Aprobado estáticamente | Sin expansión de permisos; paths remotos endurecidos. |
| APK audit | Aprobado | 18.213.405 bytes; 173 entradas; v2; cero hallazgos bloqueantes; SHA-256 publicado en el reporte Beta. |
| MariaDB efímera | Aprobado | 724 passed/1 skipped; cero→0036, check y dos ciclos 0036↔0035; tmpfs; cleanup completo; cero volúmenes. |
| QA físico | Pendiente | Seguir `BETA_1_PHYSICAL_QA_RUNBOOK.md`; ningún punto preaprobado. |

## Criterio de promoción

El resultado de esta rama está técnicamente estabilizado y puede iniciar QA físico controlado. No puede declararse release final ni QA físico aprobado mientras permanezcan bloqueados los gates conectados.
