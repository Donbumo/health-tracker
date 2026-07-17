# Historia resumida de implementación

Esta cronología conserva hitos cerrados sin convertirlos en instrucciones vigentes. Los resultados detallados, ramas, migraciones, QA y riesgos registrados en cada corte siguen disponibles en `IMPLEMENTATION_HANDOFF_ARCHIVE.md` y `AI_WORK_CONTEXT_ARCHIVE.md`.

## Hitos

- Fases 1–2: Flask/MariaDB/Docker Compose, usuarios, uploads con SHA256, schemas y captura manual con JSON generado.
- Fases 3–4: rutinas versionables, sesiones realizadas, plan vs realidad y progreso básico.
- Fase 5B: detección de schemas, asistencia de JSON no estándar y generación estándar read-only; la escritura confirmada quedó separada en `StandardImportExecutor`.
- Alpha 0.3: importación de FIT/GPX/TCX/CSV y persistencia de Activity/Route mediante el pipeline estándar.
- Alpha 0.4: exportadores avanzados, `ExportRecord`, storage generated e historial owner-only.
- Alpha 0.5: backup ZIP 1.0, restore coordinado, dedupe y reconciliación.
- Alpha 0.6/0.6.1: autenticación API v1, dispositivos, UUID públicos y consolidación de la interfaz homelab.
- Alpha 0.7: planned workouts y Mobile Sync.
- Alpha 0.8: negociación, packages, deliveries, checkpoints y completion del backend Companion.
- Alpha 0.8.1: recuperación de sesiones web, drafts e idempotencia por `client_submission_id`.
- Alpha 0.9: captura avanzada de cargas con total normalizado compatible y detalle versionado.
- Alpha 1.0: Web Daily Driver, onboarding, preferencias, Import Hub y PWA limitada a assets estáticos.
- Alpha 1.0.1: corrección de configuración runtime para la clave de firma de tokens API; tag integrado `alpha-1.0.1-runtime-security` en `1938a48`.

## Reglas de lectura

- Un hito histórico no prueba que una capability siga idéntica; revisa código/tests.
- Un conteo de pruebas pertenece al commit donde se registró y no es baseline actual automática.
- Los pendientes históricos solo permanecen activos si `ACTIVE_HANDOFF.md` o evidencia reciente los confirma.
- Las reglas canónicas actuales están en `../project-rules/`.
