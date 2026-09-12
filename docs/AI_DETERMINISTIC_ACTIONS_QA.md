# AI Operator: acciones determinísticas — QA local

Fecha: 2026-09-12. Rama: `fix/ai-operator-deterministic-actions`.
Base: `f46c5bb64759d96fc86918b0b76073f585c71d73`.
Alcance: implementación y QA local; sin merge, NAS, tag, cambios de proveedor,
modelo, timeouts, Strava ni migración. No certifica un despliegue de esta rama.

## Resultado

| Gate | Evidencia / resultado |
| --- | --- |
| Arquitectura | Intérprete genérico sobre metadata opcional de ActionCapability, antes de construir el proveedor; propuesta neutral → resolver existente → AIPlanSpec → drafts. |
| Confianza | Única interpretación, consumo completo y sin target repetido. La ambigüedad delega todo el turno, sin completar parcialmente argumentos. |
| Aliases | Verbos, entidades, slots y unidades pertenecen al dominio; metas reutilizan aliases y unidades canónicas existentes. |
| Body | Las tres formas explícitas requeridas llegan a READY; falta de peso genera NEEDS_INPUT. |
| Goal | UPDATE READY con target propio; inexistente/ambiguo queda NEEDS_INPUT, nunca CREATE. |
| Food | Desayuno con kcal/proteína llega a READY. El nombre reutiliza el tipo de comida explícito; no inventa macros ausentes. |
| Multiacción | Dos READY en un turno con valores. Sin valores, ambos pasos existen desde el primer turno. |
| Slots | Segundo turno conserva plan/draft/step IDs, contexto por paso y cero duplicados. Unidades incompatibles rechazan sin mutación; números ambiguos delegan. |
| Ambigüedad | Petición ambigua ejercida con proveedor real, sin confirmaciones. |
| Análisis | Preguntas, análisis, negación y texto residual no activan el intérprete; selección explícita de lectura/propuesta protegida. |
| Independencia | Body, goal, food y multi pasan con FakeProvider que lanza error inmediatamente; también pasa una factoría que falla si se construye. |
| Extensibilidad | Capability ficticia sleep.log descubierta por metadata, con duration/quality y continuidad de slots; schema cerrado sin campos adicionales. |
| Seguridad | Owner-only, contexto firmado, rangos/unidades, expiración, pasos aplicados y confirmación/idempotencia cubiertos. Cero recursos nuevos antes de confirmar. |
| Observabilidad | Ruta, capability IDs, conteos, IDs de campos del contrato, outcome y tiempos; sin texto ni valores extraídos. |
| MariaDB | 204 passed; target resolution, slots, IDs, idempotencia y limpieza QA incluidos. MariaDB 11.4 efímera en tmpfs, sin volúmenes persistentes. |
| Tests locales | 224 passed, 7 skipped: deterministic, operator, pending gates, foundation, templates, capabilities y data portability. |
| Migración | Sin migración nueva. Head 20260906_0039 y db check PASS en MariaDB aislada. Ciclo de migraciones existentes PASS. |
| Limpieza | Usuario QA local y asociaciones eliminados; cero residuos. Entorno MariaDB eliminado; contenedores cotidianos y volúmenes sin cambios. |

La función AI conserva sus gates de habilitación, configuración y consentimiento.
La independencia cubre indisponibilidad del proveedor en ejecución, no habilitar
una función que el administrador haya desactivado. La gramática inicial es
deliberadamente acotada; otros periodos y formulaciones conservan el proveedor.

## QA remota: exactamente dos escenarios

Ejecutada una vez con la configuración existente, sobre SQLite efímera local y
fixtures QA, sin acceso a la DB productiva y sin cambiar proveedor/modelo/timeouts.

1. `Ajústame mis metas`: provider usado, respuesta válida, cero writes.
2. Proposal Mode: `get_goals_summary` ejecutado server-side antes de invocar
   la fase proposal. Resultado `provider_malformed_tool_call` controlado, sin
   draft inválido ni write. Estado **SAFE-DEGRADED**; no bloquea estas acciones.

Sin reintentos adicionales ni smokes productivos. Limpieza: cero residuos QA.
El script opt-in reproducible es `scripts/ai/check_provider_paths.py`; no se
ejecuta en la suite habitual y no debe repetirse para forzar una salida válida.

## Verificaciones adicionales

- `compileall` de app, tests y script QA: PASS.
- Sintaxis de `ai_chat.js` y 3 tests Node de templates: PASS.
- `docker compose config --quiet`: PASS, sin mostrar configuración sensible.
- `git diff --check`: PASS.
- No se ejecutó la suite backend completa; se cubrió AI y portabilidad afectada.

## Archivos y entrega

- Runtime: `capabilities/interpreter.py`, `types.py`, `registry.py`, metadata
  en `domains/body_actions.py`, `goal_actions.py`, `nutrition_actions.py`, y
  `services/ai/conversations.py`.
- Tests: `test_ai_deterministic_actions.py`, `test_ai_operator_actions.py`,
  `test_ai_pending_gate_regressions.py`.
- QA: `scripts/ai/check_provider_paths.py`.
- Docs: `AI_FOUNDATION.md`, `HOW_TO_ADD_AN_AI_ACTION_CAPABILITY.md` y este reporte.

Commit solicitado: `fix: make common AI actions provider-independent`.
Destino de push: `origin fix/ai-operator-deterministic-actions`.
Sin bloqueadores conocidos para merge. El hash y resultado del push se entregan
en el reporte final; producción permanece sin cambios durante esta tarea.
