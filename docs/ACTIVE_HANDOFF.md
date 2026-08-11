# Handoff activo

## Estado actual

- Rama `feature/beta-1.1-ai-foundation`, worktree aislado y base Beta 1.0.1 exacta `64abf34b0c7082fc31c75b8a4bef62c5786e50d1` desde `master`.
- Beta 1.1 incorpora una base AI neutral al proveedor: fake provider sin red, conversaciones y follow-ups persistentes, 9 tools owner-only de solo lectura, evidencia/procedencia, API Bearer y UI Flask/Jinja.
- La frontera del provider valida respuestas y uso reportado; los follow-ups del fake conservan tema y periodo, y los payloads de actividad se minimizan antes de cruzar al provider.
- La migración aditiva `20260809_0037` parte del único head `20260731_0036` y crea conversaciones, mensajes, auditoría de tools y drafts owner-only.
- `AI_ENABLED` permanece desactivado por defecto. Sin provider/model configurado, el resto de la app y `/health` siguen operativos.
- El índice canónico de contexto sigue en `docs/DOCUMENTATION_INDEX.md`; configuración, límites y fronteras están en `docs/AI_FOUNDATION.md`.

## Trabajo en curso

- Implementación, documentación, migración, pruebas focales y gate MariaDB están cerrados y listos para revisión.
- No hay merge, tag, despliegue NAS ni cambios Android en alcance.

## Bloqueadores y riesgos

- No hay bloqueadores funcionales para la base AI. El único provider disponible es `fake`; todavía no existe adaptador cloud ni política operativa de retención/consentimiento para enviar datos a terceros.
- Los drafts son vistas previas `pending_confirmation`: no existe escritura ni endpoint de confirmación. Adjuntos/food image se rechazan hasta disponer de upload privado y preview.
- Las conversaciones todavía no forman parte de los contratos públicos versionados de portabilidad/export; sí se eliminan con la conversación o la cuenta mediante cascada.
- Un adapter remoto futuro debe imponer el timeout en su propia llamada de red además de respetar los límites recibidos por la frontera provider-neutral.

## Siguiente paso

- Integrar un provider cloud detrás de la abstracción existente, con timeout real, retención explícita, consentimiento y revisión de minimización antes de habilitarlo.
- Después, diseñar confirmación explícita e idempotente de drafts mediante servicios oficiales, sin permitir escritura directa desde el modelo.

## Pruebas relevantes

- `python -m compileall -q backend`: pasa.
- Focal AI local: `32 passed, 1 skipped`; la omisión es exclusivamente el caso reservado para MariaDB/Docker.
- Focal AI/API/navegación/dashboard/web: `103 passed, 2 skipped`.
- MariaDB efímera 11.4 con `tmpfs`: zero-to-head, `0037 -> 0036 -> 0037`, `flask db current/check`, limpieza y `tests/test_ai_foundation.py`: `33 passed`.
- El runner confirmó cero volúmenes persistentes, stacks diarios sin cambios y limpieza completa de contenedor, red, imagen y storage temporal.
