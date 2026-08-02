# Índice documental por dominio

Usa este archivo para cargar solo el contexto necesario. Las reglas canónicas indican qué no debe romperse; las guías explican uso/operación; historia y roadmap nunca redefinen el contrato actual.

## Contexto del repositorio

- Estado temporal: [ACTIVE_HANDOFF.md](ACTIVE_HANDOFF.md).
- Visión estable: [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).
- Arquitectura: [architecture/OVERVIEW.md](architecture/OVERVIEW.md).
- Roadmap: [ROADMAP.md](ROADMAP.md).
- Auditoría de contexto: [CONTEXT_AUDIT.md](CONTEXT_AUDIT.md).
- Decisiones documentales: [decisions/0001-context-loading.md](decisions/0001-context-loading.md).
- Historia: [history/IMPLEMENTATION_HISTORY.md](history/IMPLEMENTATION_HISTORY.md) y archivos históricos del mismo directorio.

## Uso diario y web

- Reglas: [project-rules/web-ui.md](project-rules/web-ui.md), [project-rules/web-daily-driver.md](project-rules/web-daily-driver.md).
- Primer acceso y uso: [GETTING_STARTED.md](GETTING_STARTED.md), [USER_GUIDE.md](USER_GUIDE.md), [DAILY_WORKFLOW.md](DAILY_WORKFLOW.md), [TROUBLESHOOTING_USER.md](TROUBLESHOOTING_USER.md).
- Diseño/QA: [WEB_UI_HOMELAB.md](WEB_UI_HOMELAB.md), [WEB_UI_DESIGN_SYSTEM.md](WEB_UI_DESIGN_SYSTEM.md), [WEB_UI_ACCESSIBILITY.md](WEB_UI_ACCESSIBILITY.md).
- Release/operación: [ALPHA_DEPLOYMENT.md](ALPHA_DEPLOYMENT.md), [ALPHA_RELEASE_CHECKLIST.md](ALPHA_RELEASE_CHECKLIST.md) y [ALPHA_1_5_NAS_RC_RUNBOOK.md](ALPHA_1_5_NAS_RC_RUNBOOK.md) para preflight, backup, migración, smoke, teléfono y rollback de RC1.

## Contratos e importación

- Regla transversal: [project-rules/canonical-data-contract-import-update.md](project-rules/canonical-data-contract-import-update.md).
- JSON no estándar/generación: [project-rules/phase-5b-universal-json-import-assistant.md](project-rules/phase-5b-universal-json-import-assistant.md), [project-rules/standard-json-generator-development.md](project-rules/standard-json-generator-development.md).
- Commit confirmado/auditoría: [project-rules/confirmed-standard-import.md](project-rules/confirmed-standard-import.md), [project-rules/import-audit-persistence.md](project-rules/import-audit-persistence.md).
- Import Hub/prompts: [IMPORT_HUB.md](IMPORT_HUB.md), [IMPORT_WITH_AI_PROMPTS.md](IMPORT_WITH_AI_PROMPTS.md).
- Archivos reales: [project-rules/real-file-imports.md](project-rules/real-file-imports.md), [REAL_FILE_IMPORTS.md](REAL_FILE_IMPORTS.md), [FIT_IMPORT.md](FIT_IMPORT.md), [GPX_TCX_IMPORT.md](GPX_TCX_IMPORT.md), [CSV_IMPORT.md](CSV_IMPORT.md).

## Exportación y portabilidad

- Actividades Alpha 2.0: [ALPHA_2_0_ACTIVITY_INTERCHANGE.md](ALPHA_2_0_ACTIVITY_INTERCHANGE.md), contrato [ACTIVITY_STANDARD_V1.md](ACTIVITY_STANDARD_V1.md), ubicación [ACTIVITY_LOCATION_PRIVACY.md](ACTIVITY_LOCATION_PRIVACY.md) y comparación [PLAN_VS_ACTUAL.md](PLAN_VS_ACTUAL.md); schemas `../schemas/activity_*.schema.json`, `../schemas/plan_actual_comparison.schema.json` y secciones `portable_activities`/`portable_activity_*`.

- Estudios médicos Alpha 1.9: [ALPHA_1_9_MEDICAL_RECORDS.md](ALPHA_1_9_MEDICAL_RECORDS.md), privacidad [MEDICAL_DATA_PRIVACY.md](MEDICAL_DATA_PRIVACY.md) y formato JSON/CSV [MEDICAL_LAB_FORMAT_V1.md](MEDICAL_LAB_FORMAT_V1.md); contratos `../schemas/medical_*.schema.json` y secciones `portable_medical_*`/`portable_lab_*`.
- Portabilidad selectiva Alpha 1.7: [ALPHA_1_7_DATA_PORTABILITY.md](ALPHA_1_7_DATA_PORTABILITY.md), contrato [PORTABLE_PACKAGE_FORMAT_V1.md](PORTABLE_PACKAGE_FORMAT_V1.md) y matriz [DATA_EXPORT_PRIVACY.md](DATA_EXPORT_PRIVACY.md); schemas públicos `../schemas/portable_*.schema.json` y CLI `../scripts/portability/`.
- Objetivos y recordatorios Alpha 1.8: [ALPHA_1_8_GOALS_REMINDERS.md](ALPHA_1_8_GOALS_REMINDERS.md), [NOTIFICATION_PRIVACY.md](NOTIFICATION_PRIVACY.md) y [ADHERENCE_METRICS.md](ADHERENCE_METRICS.md); contratos `../schemas/mobile_goals.schema.json`, `mobile_reminder_rules.schema.json` y `mobile_adherence.schema.json`.
- Exporters: [project-rules/exporters.md](project-rules/exporters.md), [EXPORTERS.md](EXPORTERS.md), [EXPORT_STORAGE.md](EXPORT_STORAGE.md), [ACTIVITY_ROUTE_EXPORTS.md](ACTIVITY_ROUTE_EXPORTS.md), [TRAINING_EXPORTS.md](TRAINING_EXPORTS.md).
- Restore de cuenta: [project-rules/account-restore.md](project-rules/account-restore.md), [ACCOUNT_RESTORE.md](ACCOUNT_RESTORE.md), [DATA_PORTABILITY.md](DATA_PORTABILITY.md).
- Backup ZIP: [project-rules/full-backup.md](project-rules/full-backup.md), [FULL_BACKUP.md](FULL_BACKUP.md), [BACKUP_FORMAT_1_0.md](BACKUP_FORMAT_1_0.md), [BACKUP_SECURITY.md](BACKUP_SECURITY.md), [BACKUP_RESTORE_RUNBOOK.md](BACKUP_RESTORE_RUNBOOK.md).

## API, sync y companion

- Beta 1 Android: [BETA_1_ANDROID_STABILIZATION.md](BETA_1_ANDROID_STABILIZATION.md), [ANDROID_RELEASE_READINESS.md](ANDROID_RELEASE_READINESS.md), [BETA_RELEASE_CHECKLIST.md](BETA_RELEASE_CHECKLIST.md) y [BETA_1_PHYSICAL_QA_RUNBOOK.md](BETA_1_PHYSICAL_QA_RUNBOOK.md).

- API v1: [project-rules/api-v1.md](project-rules/api-v1.md), [API_V1.md](API_V1.md), [API_AUTH.md](API_AUTH.md), [API_DEVICE_SESSIONS.md](API_DEVICE_SESSIONS.md), [API_SECURITY.md](API_SECURITY.md), [COMPANION_BOOTSTRAP.md](COMPANION_BOOTSTRAP.md).
- Mobile Sync: [project-rules/mobile-sync.md](project-rules/mobile-sync.md), [MOBILE_SYNC.md](MOBILE_SYNC.md), [SYNC_PROTOCOL_1_0.md](SYNC_PROTOCOL_1_0.md), [SYNC_IDEMPOTENCY.md](SYNC_IDEMPOTENCY.md), [SYNC_CONFLICTS.md](SYNC_CONFLICTS.md), [PLANNED_WORKOUTS.md](PLANNED_WORKOUTS.md).
- Companion delivery: [project-rules/companion-protocol.md](project-rules/companion-protocol.md), [COMPANION_PROTOCOL_1_0.md](COMPANION_PROTOCOL_1_0.md), [COMPANION_CAPABILITIES.md](COMPANION_CAPABILITIES.md), [COMPANION_WORKOUT_PACKAGE.md](COMPANION_WORKOUT_PACKAGE.md), [COMPANION_DELIVERY.md](COMPANION_DELIVERY.md), [COMPANION_PROGRESS.md](COMPANION_PROGRESS.md).
- Android Companion: [project-rules/android-companion.md](project-rules/android-companion.md), [ANDROID_COMPANION.md](ANDROID_COMPANION.md), [ANDROID_SECURITY.md](ANDROID_SECURITY.md), [ANDROID_OFFLINE_SYNC.md](ANDROID_OFFLINE_SYNC.md), [ANDROID_TESTING.md](ANDROID_TESTING.md), [ANDROID_INSTALLATION.md](ANDROID_INSTALLATION.md).
- Fuentes externas/BLE Alpha 1.6: [ALPHA_1_6_EXTERNAL_SOURCES.md](ALPHA_1_6_EXTERNAL_SOURCES.md) para arquitectura, permisos, captura/replay/dedupe y QA; [XIAOMI_S400_PROTOCOL_RESEARCH.md](XIAOMI_S400_PROTOCOL_RESEARCH.md) para separar hechos, observaciones, inferencias y desconocidos.
- Historial/progreso móvil Alpha 1.2: contratos `../schemas/mobile_history.schema.json` y `../schemas/mobile_progress.schema.json`; arquitectura y caché en [ANDROID_COMPANION.md](ANDROID_COMPANION.md) y [ANDROID_OFFLINE_SYNC.md](ANDROID_OFFLINE_SYNC.md).
- Planificación móvil Alpha 1.3: `../schemas/mobile_planning.schema.json`, `../schemas/training_plan.schema.json`, matriz y agenda/Today/packages en [ANDROID_COMPANION.md](ANDROID_COMPANION.md), persistencia/coalescing/conflictos en [ANDROID_OFFLINE_SYNC.md](ANDROID_OFFLINE_SYNC.md) y recorrido de uso en [USER_GUIDE.md](USER_GUIDE.md).
- Registro diario de salud móvil Alpha 1.4: contrato `../schemas/mobile_health.schema.json`, API/capacidades en [ANDROID_COMPANION.md](ANDROID_COMPANION.md), Room/coalescing/conflictos en [ANDROID_OFFLINE_SYNC.md](ANDROID_OFFLINE_SYNC.md), gates en [ANDROID_TESTING.md](ANDROID_TESTING.md) y recorrido en [USER_GUIDE.md](USER_GUIDE.md).
- Health Connect Alpha 1.5: disponibilidad, permisos, tipos, mapeo y límites en [ANDROID_COMPANION.md](ANDROID_COMPANION.md); tokens, ledger, borrados y cola offline en [ANDROID_OFFLINE_SYNC.md](ANDROID_OFFLINE_SYNC.md); privacidad en [ANDROID_SECURITY.md](ANDROID_SECURITY.md); matriz/gates y QA pendiente en [ANDROID_TESTING.md](ANDROID_TESTING.md); recorrido de Ajustes en [USER_GUIDE.md](USER_GUIDE.md); contrato servidor aditivo en `../schemas/mobile_health.schema.json` y [MOBILE_SYNC.md](MOBILE_SYNC.md).

## Entrenamiento web

- Cargas: [project-rules/workout-load-entry.md](project-rules/workout-load-entry.md), [WORKOUT_LOAD_ENTRY.md](WORKOUT_LOAD_ENTRY.md), [WORKOUT_LOAD_MODES.md](WORKOUT_LOAD_MODES.md), [WORKOUT_LOAD_CALCULATIONS.md](WORKOUT_LOAD_CALCULATIONS.md).
- Recuperación/idempotencia: [project-rules/workout-session-recovery.md](project-rules/workout-session-recovery.md), [WORKOUT_SESSION_RECOVERY.md](WORKOUT_SESSION_RECOVERY.md), [WORKOUT_DRAFTS.md](WORKOUT_DRAFTS.md), [WORKOUT_SUBMISSION_IDEMPOTENCY.md](WORKOUT_SUBMISSION_IDEMPOTENCY.md).

## Historial y documentos no normativos

- [history/AI_WORK_CONTEXT_ARCHIVE.md](history/AI_WORK_CONTEXT_ARCHIVE.md): antiguo contexto maestro, solo trazabilidad.
- [history/IMPLEMENTATION_HANDOFF_ARCHIVE.md](history/IMPLEMENTATION_HANDOFF_ARCHIVE.md): handoffs acumulados y resultados de QA históricos.
- [history/PHASE_5B_ORIGINAL_PROPOSAL.md](history/PHASE_5B_ORIGINAL_PROPOSAL.md): propuesta original; contiene ejemplos superados.

No leas `history/` para una tarea normal. Si un archivo histórico contradice schemas, pruebas, reglas o código vigente, pierde prioridad.
