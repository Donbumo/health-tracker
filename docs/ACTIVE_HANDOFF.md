# Handoff activo

Actualizado: 2026-07-17.

## Estado actual

- Base integrada comprobada: commit `1938a48`, tag `alpha-1.0.1-runtime-security`.
- La aplicación web Alpha 1.0, captura avanzada de cargas, recuperación de sesiones, API v1, Mobile Sync y Companion backend están integrados en la base actual.
- APK Android, app de reloj, Bluetooth, telemetría continua e integraciones privadas de fabricantes no están implementados.

## Trabajo en curso

- Rama: `chore/optimize-agent-context`.
- Objetivo: separar contexto caliente, tibio y frío sin cambiar comportamiento de la aplicación.
- Alcance: instrucciones de agentes, índice, arquitectura documental, historia, roadmap y pruebas documentales.
- Código funcional, modelos, migraciones y schemas públicos: sin cambios previstos.

## Decisiones activas

- `AGENTS.md` es un router breve; no ordena leer `docs/PROJECT_CONTEXT.md` para toda tarea.
- Este archivo contiene solo estado temporal. Los hitos cerrados viven en `history/IMPLEMENTATION_HANDOFF_ARCHIVE.md` y `history/IMPLEMENTATION_HISTORY.md`.
- Las reglas permanentes viven en `project-rules/`; los contratos públicos, en `../schemas/`.
- El índice por dominio es `DOCUMENTATION_INDEX.md`.

## Archivos relevantes

- `../AGENTS.md`
- `DOCUMENTATION_INDEX.md`
- `CONTEXT_AUDIT.md`
- `PROJECT_CONTEXT.md`
- `decisions/0001-context-loading.md`

## Bloqueadores y riesgos

- No hay bloqueador conocido para esta reorganización.
- El sign-off visual real de tema claro de Alpha 1.0 y la rotación de la credencial señalada durante QA siguen siendo pendientes operativos históricos; no deben marcarse como resueltos sin evidencia nueva.

## Siguiente paso

Revisar el diff documental y decidir si se integra la reorganización. No hay commit, push, merge ni tag realizados por esta tarea.

## Pruebas relevantes

- `backend/tests/test_active_handoff.py`: `1 passed`.
- Comprobación de enlaces Markdown locales: sin referencias rotas.
- Comprobación de rutas estructurales requeridas: todas existen.
- `git diff --check`: limpio; solo avisos informativos de normalización LF/CRLF en Windows.
- No se ejecutó la suite funcional completa porque no cambió código de aplicación, modelos, migraciones ni schemas.
- La última validación funcional histórica de Alpha 1.0 está preservada en `history/IMPLEMENTATION_HANDOFF_ARCHIVE.md`; no se vuelve a declarar como resultado de esta tarea documental.
