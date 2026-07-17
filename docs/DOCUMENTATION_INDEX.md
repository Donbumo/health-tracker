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
- Release/operación: [ALPHA_DEPLOYMENT.md](ALPHA_DEPLOYMENT.md), [ALPHA_RELEASE_CHECKLIST.md](ALPHA_RELEASE_CHECKLIST.md).

## Contratos e importación

- Regla transversal: [project-rules/canonical-data-contract-import-update.md](project-rules/canonical-data-contract-import-update.md).
- JSON no estándar/generación: [project-rules/phase-5b-universal-json-import-assistant.md](project-rules/phase-5b-universal-json-import-assistant.md), [project-rules/standard-json-generator-development.md](project-rules/standard-json-generator-development.md).
- Commit confirmado/auditoría: [project-rules/confirmed-standard-import.md](project-rules/confirmed-standard-import.md), [project-rules/import-audit-persistence.md](project-rules/import-audit-persistence.md).
- Import Hub/prompts: [IMPORT_HUB.md](IMPORT_HUB.md), [IMPORT_WITH_AI_PROMPTS.md](IMPORT_WITH_AI_PROMPTS.md).
- Archivos reales: [project-rules/real-file-imports.md](project-rules/real-file-imports.md), [REAL_FILE_IMPORTS.md](REAL_FILE_IMPORTS.md), [FIT_IMPORT.md](FIT_IMPORT.md), [GPX_TCX_IMPORT.md](GPX_TCX_IMPORT.md), [CSV_IMPORT.md](CSV_IMPORT.md).

## Exportación y portabilidad

- Exporters: [project-rules/exporters.md](project-rules/exporters.md), [EXPORTERS.md](EXPORTERS.md), [EXPORT_STORAGE.md](EXPORT_STORAGE.md), [ACTIVITY_ROUTE_EXPORTS.md](ACTIVITY_ROUTE_EXPORTS.md), [TRAINING_EXPORTS.md](TRAINING_EXPORTS.md).
- Restore de cuenta: [project-rules/account-restore.md](project-rules/account-restore.md), [ACCOUNT_RESTORE.md](ACCOUNT_RESTORE.md), [DATA_PORTABILITY.md](DATA_PORTABILITY.md).
- Backup ZIP: [project-rules/full-backup.md](project-rules/full-backup.md), [FULL_BACKUP.md](FULL_BACKUP.md), [BACKUP_FORMAT_1_0.md](BACKUP_FORMAT_1_0.md), [BACKUP_SECURITY.md](BACKUP_SECURITY.md), [BACKUP_RESTORE_RUNBOOK.md](BACKUP_RESTORE_RUNBOOK.md).

## API, sync y companion

- API v1: [project-rules/api-v1.md](project-rules/api-v1.md), [API_V1.md](API_V1.md), [API_AUTH.md](API_AUTH.md), [API_DEVICE_SESSIONS.md](API_DEVICE_SESSIONS.md), [API_SECURITY.md](API_SECURITY.md), [COMPANION_BOOTSTRAP.md](COMPANION_BOOTSTRAP.md).
- Mobile Sync: [project-rules/mobile-sync.md](project-rules/mobile-sync.md), [MOBILE_SYNC.md](MOBILE_SYNC.md), [SYNC_PROTOCOL_1_0.md](SYNC_PROTOCOL_1_0.md), [SYNC_IDEMPOTENCY.md](SYNC_IDEMPOTENCY.md), [SYNC_CONFLICTS.md](SYNC_CONFLICTS.md), [PLANNED_WORKOUTS.md](PLANNED_WORKOUTS.md).
- Companion delivery: [project-rules/companion-protocol.md](project-rules/companion-protocol.md), [COMPANION_PROTOCOL_1_0.md](COMPANION_PROTOCOL_1_0.md), [COMPANION_CAPABILITIES.md](COMPANION_CAPABILITIES.md), [COMPANION_WORKOUT_PACKAGE.md](COMPANION_WORKOUT_PACKAGE.md), [COMPANION_DELIVERY.md](COMPANION_DELIVERY.md), [COMPANION_PROGRESS.md](COMPANION_PROGRESS.md).

## Entrenamiento web

- Cargas: [project-rules/workout-load-entry.md](project-rules/workout-load-entry.md), [WORKOUT_LOAD_ENTRY.md](WORKOUT_LOAD_ENTRY.md), [WORKOUT_LOAD_MODES.md](WORKOUT_LOAD_MODES.md), [WORKOUT_LOAD_CALCULATIONS.md](WORKOUT_LOAD_CALCULATIONS.md).
- Recuperación/idempotencia: [project-rules/workout-session-recovery.md](project-rules/workout-session-recovery.md), [WORKOUT_SESSION_RECOVERY.md](WORKOUT_SESSION_RECOVERY.md), [WORKOUT_DRAFTS.md](WORKOUT_DRAFTS.md), [WORKOUT_SUBMISSION_IDEMPOTENCY.md](WORKOUT_SUBMISSION_IDEMPOTENCY.md).

## Historial y documentos no normativos

- [history/AI_WORK_CONTEXT_ARCHIVE.md](history/AI_WORK_CONTEXT_ARCHIVE.md): antiguo contexto maestro, solo trazabilidad.
- [history/IMPLEMENTATION_HANDOFF_ARCHIVE.md](history/IMPLEMENTATION_HANDOFF_ARCHIVE.md): handoffs acumulados y resultados de QA históricos.
- [history/PHASE_5B_ORIGINAL_PROPOSAL.md](history/PHASE_5B_ORIGINAL_PROPOSAL.md): propuesta original; contiene ejemplos superados.

No leas `history/` para una tarea normal. Si un archivo histórico contradice schemas, pruebas, reglas o código vigente, pierde prioridad.
