# Handoff activo

## Estado actual

- Rama `feature/beta-1.1-ai-foundation`, worktree aislado y base Beta 1.0.1 exacta `64abf34b0c7082fc31c75b8a4bef62c5786e50d1` desde `master`.
- Beta 1.1 incorpora una base AI neutral al proveedor: fake provider sin red, conversaciones y follow-ups persistentes, 9 tools owner-only de solo lectura, evidencia/procedencia, API Bearer y UI Flask/Jinja.
- La migración aditiva `20260809_0037` parte del único head `20260731_0036` y crea conversaciones, mensajes, auditoría de tools y drafts owner-only.
- `AI_ENABLED` permanece desactivado por defecto. Sin provider/model configurado, el resto de la app y `/health` siguen operativos.
- El índice canónico de contexto sigue en `docs/DOCUMENTATION_INDEX.md`; los límites de AI están en `docs/AI_FOUNDATION.md`.

## Trabajo en curso

- Implementación, documentación, migración, pruebas focales, gate MariaDB y QA visual están terminados.
- Solo resta crear los commits lógicos autorizados y publicar esta rama; no hay merge, tag ni despliegue en alcance.

## Bloqueadores y riesgos

- No hay bloqueadores funcionales para la base AI. El único provider disponible es `fake`; todavía no existe adaptador cloud ni política operativa de retención/consentimiento para enviar datos a terceros.
- Los drafts son vistas previas `pending_confirmation`: no existe escritura ni endpoint de confirmación. Adjuntos/food image se rechazan hasta disponer de upload privado y preview.
- Las conversaciones todavía no forman parte de los contratos públicos de portabilidad/export.
- La suite local completa conserva 22 fallos ajenos a AI porque este checkout no contiene fixtures QA FIT/GPX/TCX generadas. Alembic SQLite desde cero conserva además una incompatibilidad histórica en `20260705_0015`; el gate oficial MariaDB sí pasa.

## Siguiente paso

- Integrar un provider cloud detrás de la abstracción existente, con timeout real, retención explícita, consentimiento y revisión de minimización antes de habilitarlo.
- Después, diseñar confirmación explícita e idempotente de drafts mediante servicios oficiales, sin permitir escritura directa desde el modelo.

## Pruebas relevantes

- `python -m compileall -q backend`: pasa.
- Focal local AI/API/navegación/dashboard: `84 passed, 2 skipped`.
- MariaDB efímera 11.4 con `tmpfs`: zero-to-head, `0037 -> 0036 -> 0037`, `flask db current/check`, limpieza y `tests/test_ai_foundation.py`: `29 passed`.
- Suite backend completa: `751 passed, 11 skipped, 23 failed`; 22 fallos son únicamente fixtures FIT/GPX/TCX ausentes y el fallo de estructura de este handoff quedó corregido después de esa corrida.
- QA visual dark mode: lista y conversación verificadas entre 360 y 1366 px, sin overflow, solapamientos ni errores de consola; tokens light mode conservan el sistema visual existente.
