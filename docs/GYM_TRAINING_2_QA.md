# Gym Training 2.0 — entrega y QA

Fecha: 2026-09-13. Rama: `feature/gym-training-2`, basada en `origin/master`
fe82b2f. Un checkout, el Compose existente y una instancia MariaDB local.
Solo datos ficticios en SQLite temporal y schema MariaDB separado de QA.
No se migró la base de uso real ni se desplegó en NAS.

| # | Área | Resultado |
| --- | --- | --- |
| 1 | Modelo anterior | Auditados modelos, import/export/restore, catálogo, web, cargas, timezone, dashboard, AI, progreso y borrado; detalle en GYM_TRAINING_2.md. |
| 2 | Arquitectura | Se reutiliza un único dominio training y sus contratos canónicos. |
| 3 | Program | TrainingPlan y selección gym_active por usuario. |
| 4 | Revision | TrainingPlanVersion conserva snapshot/SHA inmutables; revisión optimista detecta cambios concurrentes. |
| 5 | Days | Nombres libres y orden explícito; posición dentro del snapshot, sin asumir calendario. |
| 6 | Prescriptions | Series, reps/rangos, carga/unidad, RIR/RPE, descanso y notas opcionales. |
| 7 | Sessions | Se crean solo al iniciar; estados en curso, completada y cerrada incompleta. |
| 8 | Set performance | Solo se persiste una serie después de confirmar datos validados. |
| 9 | Previous performance | Mismo programa prioritario, fallback global y aliases propios; solo cargas compatibles. |
| 10 | Suggestions | Anterior → objetivo → vacío; se mantiene la separación de series reales. |
| 11 | Fast logging | Carga total/reps/esfuerzo, copiar, repetir, incrementos kg/lb y flujo Enter. |
| 12 | Autosave/resume | Persistencia por serie, borrador local de campos y reanudación exacta; retries idempotentes. |
| 13 | Finish | Resumen con duración, series, volumen y referencia anterior; cierre incompleto diferenciado. |
| 14 | Progress | Historial global, mejor carga/serie por reps, volumen, tendencia y esfuerzo promedio; reutiliza comparabilidad existente. |
| 15 | Program UI | Tarjetas de días, programa activo, crear/importar/editar, versiones, historial y progreso. |
| 16 | Import assistant | Manual, presets y archivos; preview/mapping/corrección/confirmación separados. |
| 17 | CSV | UTF-8, delimitadores allowlisted; cargas y esfuerzo como objetivos. |
| 18 | XLSX | Una hoja, límites de ZIP/XML, rechazo de macros/fórmulas/enlaces/entidades. |
| 19 | JSON | Filas, draft de días y documento estándar; identidades externas resueltas por servidor. |
| 20 | Text | Texto tabular con encabezados; prosa libre/PDF/fotos pendientes de parser futuro. |
| 21 | Resolution | Catálogo/aliases propios y equivalencias explícitas; sin fuzzy agresivo. |
| 22 | Unresolved | Selección manual o creación de identidad; preview nuevo antes de confirmar. |
| 23 | Imported targets | RPE/RIR/carga no generan sesiones ni performances. |
| 24 | Updates | Nuevo contenido genera snapshot; retry no duplica; revertir contenido reutiliza su snapshot histórico. |
| 25 | Legacy | Sin borrado o vínculos fabricados; estado legacy completed por defecto. Restore conserva sesiones distintas del mismo segundo. |
| 26 | Dashboard | Sesiones abiertas excluidas de métricas completadas; regresiones focales aprobadas. |
| 27 | AI | Nuevas lecturas neutrales y compatibilidad summary/history; providers/model/timeouts intactos. |
| 28 | Coach | Cuatro contratos de acción reservados, ninguna escritura habilitada. |
| 29 | Mobile | 360/390/430/768/1024/1366 × 844; inputs 16 px y targets 44 px; teclado probado con navegador, sin dispositivo físico. |
| 30 | Queries | Contexto precargado, sin N+1 por serie, máximo ocho consultas en prueba y límite de 2000 apariciones. |
| 31 | Migration | 0040 aditiva; upgrade desde vacío y downgrade/upgrade sobre QA; un head, db check sin operaciones pendientes. |
| 32 | Focales | Último bloque gym/recovery: 42 passed, 1 skipped. Bloque transversal API/sync/export/restore/portabilidad: 123 passed, 3 skipped. |
| 33 | MariaDB | Última ejecución en contenedor: 29 passed, incluyendo prueba real de carreras de inicio/serie y cascada de borrado del usuario ficticio. |
| 34 | Suite completa | Ejecutada UNA vez: 1023 passed, 3 failed, 15 skipped. Los tres fallos se corrigieron y sus suites se repitieron: 135 passed, 3 skipped. No se presenta como una segunda suite completa verde. |
| 35 | Visual | 36 comprobaciones por recorrido, consola sin errores, recuperación de edición/series, repeat, teclado, finish, anterior, progreso con datos y XLSX confirm. Capturas 390/1366 revisadas. |
| 36 | Archivos | Blueprint gym, cuatro servicios gym, parser, seis templates, CSS/tres JS, migración, fixtures/tests/scripts/docs; integración focal en modelos, import/export/restore, sync, dashboard/AI y schemas. |
| 37 | Commit | Mensaje de entrega: `feat: redesign gym training programs and workout flow`; hash exacto en `git log -1` de la rama publicada. |
| 38 | Git | Comprobar working tree limpio y sincronizado con origin tras commit/push; no merge ni tag. Resultado final comunicado en la entrega. |
| 39 | Límites | Captura rápida de total externo; modalidades corporales/asistencia/duración requieren editor avanzado. Progreso normalizado en kg; PDF/foto/Coach no habilitados. No QA física ni despliegue NAS. |
| 40 | Review | Implementación y QA local listas para revisión de código y alcance; aplicación de migración a datos de uso real queda para el despliegue autorizado. |

## Evidencia y reproducción

La suite completa detectó dos expectativas de interfaz antiguas (allowlist de
tools y enlace de importación) y una selección de lectura por orden de capabilities.
Se actualizaron las expectativas al contrato nuevo y se conservaron las lecturas
antiguas primero para mantener training summary. Pruebas focales adicionales
cubrieron restore, recuperación, optimistic conflict, ownership y CSV seguro.
Los conteos anteriores son ejecuciones solapadas, no deben sumarse.

Compileall, tres `node --check`, 12 tests Node, Compose config con variables
ficticias explícitas, Alembic current/check y git diff --check aprobados.
La comprobación Compose no leyó `.env` ni arrancó otra pila.

Reproducción visual: iniciar `scripts/gym/qa_app.py` con FLASK_SKIP_DOTENV=1 y
ejecutar `node scripts/gym/visual_qa.cjs <directorio-temporal-de-salida>` con
Playwright disponible. Usa Edge headless y un usuario exclusivamente ficticio.
La salida report.json incluye mediciones por pantalla; las capturas contienen
únicamente fixtures QA. Los artefactos locales no se añaden al repositorio.

Las limitaciones son explícitas: una simulación de viewport no demuestra la
experiencia de un teléfono físico, y un downgrade tras uso real descartaría
los estados nuevos. La base de datos del usuario permanece sin modificar.
