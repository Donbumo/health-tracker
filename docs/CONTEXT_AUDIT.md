# Auditoría del contexto para agentes

Fecha: 2026-07-17. Alcance: instrucciones jerárquicas, documentos usados como contexto, README, reglas de dominio, handoffs, historia, decisiones y configuración local para Codex.

## Inventario y hallazgos

- Existía un único `AGENTS.md` versionado, sin `AGENTS.override.md` ni instrucciones locales.
- No existían `.codex/`, ADRs ni plantillas de tareas/planes versionadas.
- `android-app/` y `watch-app/` no contienen archivos versionados; no se crearon instrucciones artificiales.
- Había 65 Markdown bajo `docs/` y 16 reglas en `docs/project-rules/`.
- Todos los enlaces Markdown relativos resolvían antes del cambio; las referencias problemáticas eran órdenes de lectura obsoletas, no targets inexistentes.
- El árbol inicial estaba limpio en `chore/optimize-agent-context`, base `1938a48`.

## Consumo aproximado antes del cambio

| Archivo | Líneas | Bytes | Tokens aprox. |
| --- | ---: | ---: | ---: |
| `AGENTS.md` | 266 | 10,045 | 2,511 |
| `docs/AI_WORK_CONTEXT.md` | 322 | 18,877 | 4,719 |
| `docs/PROJECT_CONTEXT.md` | 1,628 | 42,997 | 10,749 |
| `docs/ACTIVE_HANDOFF.md` | 297 | 23,853 | 5,963 |
| `README.md` | 686 | 38,856 | 9,714 |

`AGENTS.md` ordenaba cargar siempre, además de sí mismo, `AI_WORK_CONTEXT`, `PROJECT_CONTEXT`, la regla transversal y la propuesta Fase 5B: unas 108 KB / 27 mil tokens antes de inspeccionar el dominio. Siguiendo el orden secundario con handoff y README, el costo potencial superaba 40 mil tokens.

## Resultado de la reorganización

| Contexto | Líneas | Bytes | Tokens aprox. |
| --- | ---: | ---: | ---: |
| Raíz automática (`AGENTS.md`) | 75 | 4,547 | 1,137 |
| Tarea backend (raíz + `backend/AGENTS.md`) | 122 | 6,644 | 1,661 |
| Tarea de schemas (raíz + `schemas/AGENTS.md`) | 88 | 5,809 | 1,452 |
| Handoff, solo si se necesita | 49 | 2,427 | 607 |
| README humano | 83 | 4,187 | 1,047 |

El contexto raíz bajó 72% en líneas y 55% en bytes. El README bajó 88% en líneas y 89% en bytes. La lectura automática ya no arrastra ningún documento largo; una tarea pequeña empieza con unas 1,100 tokens de instrucciones del repositorio.

## Problemas transversales encontrados

- Estado, historia, reglas y roadmap mezclados en tres documentos maestros.
- Varias ramas antiguas declaradas simultáneamente como activas.
- Seguridad, precedencia, pipeline y comandos duplicados en `AGENTS.md`, `AI_WORK_CONTEXT.md`, `PROJECT_CONTEXT.md` y `ACTIVE_HANDOFF.md`.
- Un test documental exigía una afirmación obsoleta sobre restore para mantener compatibilidad textual.
- La propuesta Fase 5B contradecía el schema canónico (`body_water_percent` frente a `water_percent`) y el preview read-only vigente.
- `PROJECT_CONTEXT.md` incluía estructuras/rutas sugeridas ya reemplazadas por código real y preferencias de entrenamiento específicas impropias de documentación versionada.

## Inventario por archivo

“Automático” significa descubierto jerárquicamente; “bajo demanda” significa que el router/índice lo abre solo para el dominio indicado.

| Archivo | Propósito | Problema encontrado | Acción | Carga |
| --- | --- | --- | --- | --- |
| `AGENTS.md` | Instrucciones globales | Era contexto maestro de 266 líneas y forzaba lecturas extensas | Reescrito como router caliente | Automática |
| `backend/AGENTS.md` | Reglas de backend/migraciones/pruebas | No existía; reglas backend estaban globales | Creado cerca del código | Automática solo bajo `backend/` |
| `schemas/AGENTS.md` | Contrato público y cambios de schema | No existía; reglas de schemas estaban globales | Creado cerca de `schemas/` | Automática solo bajo `schemas/` |
| `README.md` | Entrada humana y operación | Mezclaba hitos, guías completas y antiguo protocolo de handoff | Reescrito como portada breve con enlaces canónicos | Bajo demanda |
| `docs/ACTIVE_HANDOFF.md` | Estado temporal | Acumulaba 297 líneas de historia | Reescrito compacto; historia archivada | Bajo demanda para continuidad |
| `docs/AI_WORK_CONTEXT.md` | Segundo contexto maestro | Duplicado, contradictorio y obsoleto | Movido a `history/AI_WORK_CONTEXT_ARCHIVE.md` | Nunca por defecto |
| `docs/PROJECT_CONTEXT.md` | Visión completa | Mezclaba estado, roadmap, historia y preferencias específicas | Reescrito como contexto estable | Bajo demanda |
| `docs/DOCUMENTATION_INDEX.md` | Router por dominio | No existía | Creado | Bajo demanda desde `AGENTS.md` |
| `docs/CONTEXT_AUDIT.md` | Inventario y trazabilidad de esta reorganización | No existía | Creado | Auditoría bajo demanda |
| `docs/architecture/OVERVIEW.md` | Arquitectura ejecutable resumida | Arquitectura estaba mezclada con roadmap | Creado | Bajo demanda |
| `docs/decisions/0001-context-loading.md` | ADR de contexto caliente/tibio/frío | No había ADR de esta decisión | Creado | Bajo demanda |
| `docs/ROADMAP.md` | Funciones futuras/no comprobadas | Roadmap estaba mezclado con estado actual | Creado | Bajo demanda |
| `docs/history/IMPLEMENTATION_HISTORY.md` | Cronología resumida | Hitos estaban repetidos en cuatro archivos | Creado como fuente histórica corta | Bajo demanda |
| `docs/history/IMPLEMENTATION_HANDOFF_ARCHIVE.md` | Handoffs y QA históricos | Antes se cargaba como estado activo | Movido y marcado histórico | Solo investigación histórica |
| `docs/history/AI_WORK_CONTEXT_ARCHIVE.md` | Contexto maestro anterior | Antes competía con fuentes vigentes | Movido y desactivado | Solo investigación histórica |
| `docs/history/PHASE_5B_ORIGINAL_PROPOSAL.md` | Propuesta detallada Fase 5B | Ejemplos/estado superados | Movido y marcado no normativo | Solo historia de diseño |
| `docs/project-rules/canonical-data-contract-import-update.md` | Regla transversal de contrato/import/update | Extensa, pero especializada; duplicada en maestros | Conservada fría y enlazada sin copiar | Bajo demanda |
| `docs/project-rules/phase-5b-universal-json-import-assistant.md` | Regla vigente de JSON asistido | Mezclaba propuesta, futuro y contrato contradictorio | Sustituida por regla actual concisa | Bajo demanda |
| `docs/project-rules/standard-json-generator-development.md` | Invariantes del generador | Se leía demasiado ampliamente | Conservada; router limita su uso al dominio | Bajo demanda |
| `docs/project-rules/confirmed-standard-import.md` | Commit confirmado estándar | Sin problema estructural; estado copiado en maestros | Conservada como fuente única | Bajo demanda |
| `docs/project-rules/import-audit-persistence.md` | Auditoría `ImportRun` | Sin problema estructural | Conservada | Bajo demanda |
| `docs/project-rules/real-file-imports.md` | FIT/GPX/TCX/CSV de entrada | Sin problema estructural | Conservada | Bajo demanda |
| `docs/project-rules/exporters.md` | Invariantes de exportación | Duplicada parcialmente en maestros | Conservada como fuente única | Bajo demanda |
| `docs/project-rules/account-restore.md` | Restore JSON de cuenta | Duplicada parcialmente en handoff/README | Conservada como fuente única | Bajo demanda |
| `docs/project-rules/full-backup.md` | Backup ZIP | Duplicada parcialmente en handoff/README | Conservada como fuente única | Bajo demanda |
| `docs/project-rules/api-v1.md` | Bearer/API v1 | Duplicada parcialmente en contexto operativo | Conservada como fuente única | Bajo demanda |
| `docs/project-rules/mobile-sync.md` | Sync móvil | Duplicada parcialmente en contexto operativo | Conservada como fuente única | Bajo demanda |
| `docs/project-rules/companion-protocol.md` | Packages/deliveries/checkpoints | Duplicada parcialmente en contexto operativo | Conservada como fuente única | Bajo demanda |
| `docs/project-rules/web-ui.md` | Jinja/CSS/navegación | Sin problema estructural | Conservada | Bajo demanda |
| `docs/project-rules/web-daily-driver.md` | Flujo web cotidiano/PWA | Sin problema estructural | Conservada | Bajo demanda |
| `docs/project-rules/workout-load-entry.md` | Carga avanzada | Sin problema estructural | Conservada | Bajo demanda |
| `docs/project-rules/workout-session-recovery.md` | Drafts/CSRF/idempotencia | Sin problema estructural | Conservada | Bajo demanda |
| `docs/GETTING_STARTED.md` | Primer acceso | Se alcanzaba a través del README completo | Indexado como guía de usuario | Bajo demanda |
| `docs/USER_GUIDE.md` | Uso cotidiano | Sin problema estructural | Indexado | Bajo demanda |
| `docs/DAILY_WORKFLOW.md` | Flujo diario | Sin problema estructural | Indexado | Bajo demanda |
| `docs/TROUBLESHOOTING_USER.md` | Soporte de usuario | Sin problema estructural | Indexado | Bajo demanda |
| `docs/WEB_UI_HOMELAB.md` | Estado/diseño web | Contiene cortes de release, no regla | Clasificado como guía/QA | Bajo demanda |
| `docs/WEB_UI_DESIGN_SYSTEM.md` | Componentes visuales | Sin problema estructural | Indexado | Bajo demanda |
| `docs/WEB_UI_ACCESSIBILITY.md` | Accesibilidad mínima | Sin problema estructural | Indexado | Bajo demanda |
| `docs/IMPORT_HUB.md` | Capacidades visibles de import | Sin problema estructural | Indexado | Bajo demanda |
| `docs/IMPORT_WITH_AI_PROMPTS.md` | Prompts locales de preparación | Sin problema estructural | Indexado | Bajo demanda |
| `docs/REAL_FILE_IMPORTS.md` | Guía de imports de archivo | Repite la regla en forma narrativa | Conservada como guía, subordinada a la regla | Bajo demanda |
| `docs/FIT_IMPORT.md` | Detalle FIT | Sin problema estructural | Indexado | Bajo demanda |
| `docs/GPX_TCX_IMPORT.md` | Detalle GPX/TCX | Sin problema estructural | Indexado | Bajo demanda |
| `docs/CSV_IMPORT.md` | Detalle CSV | Sin problema estructural | Indexado | Bajo demanda |
| `docs/EXPORTERS.md` | Matriz/uso de exports | Repite invariantes de la regla | Conservada como guía | Bajo demanda |
| `docs/EXPORT_STORAGE.md` | Integridad/storage de export | Sin problema estructural | Indexado | Bajo demanda |
| `docs/ACTIVITY_ROUTE_EXPORTS.md` | Formatos activity/route | Sin problema estructural | Indexado | Bajo demanda |
| `docs/TRAINING_EXPORTS.md` | Formatos de entrenamiento | Sin problema estructural | Indexado | Bajo demanda |
| `docs/ACCOUNT_RESTORE.md` | Uso de restore de cuenta | Repite parte de la regla canónica | Conservada como guía | Bajo demanda |
| `docs/DATA_PORTABILITY.md` | Export/restore semántico | Mezcla estado y futuro en poca escala | Clasificado como guía fría | Bajo demanda |
| `docs/FULL_BACKUP.md` | Uso de backup ZIP | Repite parte de la regla | Conservada como guía | Bajo demanda |
| `docs/BACKUP_FORMAT_1_0.md` | Contrato de manifest/layout | Contrato especializado | Conservado | Bajo demanda |
| `docs/BACKUP_SECURITY.md` | Threat model de backup | Sin problema estructural | Conservado | Bajo demanda |
| `docs/BACKUP_RESTORE_RUNBOOK.md` | Operación/reconciliación | Sin problema estructural | Conservado | Bajo demanda |
| `docs/API_V1.md` | Mapa de API | Sin problema estructural | Indexado | Bajo demanda |
| `docs/API_AUTH.md` | Flujo auth API | Sin problema estructural | Indexado | Bajo demanda |
| `docs/API_DEVICE_SESSIONS.md` | Dispositivos/sesiones | Sin problema estructural | Indexado | Bajo demanda |
| `docs/API_SECURITY.md` | Seguridad API | Sin problema estructural | Indexado | Bajo demanda |
| `docs/COMPANION_BOOTSTRAP.md` | Bootstrap API | Sin problema estructural | Indexado | Bajo demanda |
| `docs/MOBILE_SYNC.md` | Guía sync | Sin problema estructural | Indexado | Bajo demanda |
| `docs/SYNC_PROTOCOL_1_0.md` | Contrato sync | Sin problema estructural | Indexado | Bajo demanda |
| `docs/SYNC_IDEMPOTENCY.md` | Idempotencia sync | Sin problema estructural | Indexado | Bajo demanda |
| `docs/SYNC_CONFLICTS.md` | Conflictos/revisiones | Sin problema estructural | Indexado | Bajo demanda |
| `docs/PLANNED_WORKOUTS.md` | Planned workouts | Sin problema estructural | Indexado | Bajo demanda |
| `docs/COMPANION_PROTOCOL_1_0.md` | Flujo companion 1.0 | Sin problema estructural | Indexado | Bajo demanda |
| `docs/COMPANION_CAPABILITIES.md` | Capability negotiation | Sin problema estructural | Indexado | Bajo demanda |
| `docs/COMPANION_WORKOUT_PACKAGE.md` | Package 1.0 | Sin problema estructural | Indexado | Bajo demanda |
| `docs/COMPANION_DELIVERY.md` | Estado de deliveries | Sin problema estructural | Indexado | Bajo demanda |
| `docs/COMPANION_PROGRESS.md` | Checkpoint/completion | Sin problema estructural | Indexado | Bajo demanda |
| `docs/WORKOUT_LOAD_ENTRY.md` | Uso/semántica de carga | Sin problema estructural | Indexado | Bajo demanda |
| `docs/WORKOUT_LOAD_MODES.md` | Modos permitidos | Sin problema estructural | Indexado | Bajo demanda |
| `docs/WORKOUT_LOAD_CALCULATIONS.md` | Cálculos/detalle | Sin problema estructural | Indexado | Bajo demanda |
| `docs/WORKOUT_SESSION_RECOVERY.md` | Guía de recuperación | Sin problema estructural | Indexado | Bajo demanda |
| `docs/WORKOUT_DRAFTS.md` | Borradores local/servidor | Sin problema estructural | Indexado | Bajo demanda |
| `docs/WORKOUT_SUBMISSION_IDEMPOTENCY.md` | Idempotencia web | Sin problema estructural | Indexado | Bajo demanda |
| `docs/ALPHA_DEPLOYMENT.md` | Despliegue privado | Conservaba rama y afirmaciones de restore superadas | Corregido y clasificado como runbook | Bajo demanda |
| `docs/ALPHA_RELEASE_CHECKLIST.md` | Gate de release | Acumula checks por versión | Conservado como checklist frío | Bajo demanda |

## Información derivable del código

No debe copiarse a contexto caliente:

- lista exacta de targets (`SUPPORTED_TARGETS`);
- rutas Flask y blueprints;
- modelos/tablas/columnas;
- head de migración;
- formatos/capabilities registrados;
- conteos actuales de pruebas;
- ramas y commit activos.

Estos datos se inspeccionan en código, tests, migraciones o Git cuando una tarea los necesita.

## Criterio de mantenimiento

- Reemplaza el contenido de `ACTIVE_HANDOFF.md`; no agregues una cronología.
- Agrega una regla solo si contiene invariantes, no estado.
- Agrega un `AGENTS.md` local solo cuando un subárbol tenga reglas distintas.
- Si un documento narrativo repite una regla, enlaza la fuente canónica y conserva solo explicación operativa.
- Archiva propuestas superadas con aviso no normativo o elimínalas si no aportan trazabilidad.
