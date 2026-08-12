# Handoff activo

## Estado actual

- Rama `feature/beta-1.1-ai-foundation`; Iteration 2 convierte la base AI en release candidate Beta 1.1.
- `FakeAIProvider` sigue sin red. `OpenAIResponsesProvider` usa Responses API mediante HTTP liviano, `store=false`, timeout, tools/function calls, usage y errores seguros; tests usan transporte mock.
- AI remota exige consentimiento explícito por usuario y muestra provider/model/privacidad en `/ai`. `AI_ENABLED=false` permanece como default seguro.
- El contexto está acotado por mensajes, caracteres, turnos, tools, rondas, output y usage total.
- `body_measurement` y `food_entry` usan preview editable y confirmación owner-only por servicios oficiales. Bloqueo de fila + `client_event_id` determinista impiden duplicados, incluso concurrentes en MariaDB.
- Conversaciones AI son portables en `health-tracker-portable-v1`; se omiten credenciales, argumentos/provider internals y chain-of-thought.
- Migración `20260811_0038` añade consentimiento y metadata de aplicación de drafts sobre head `20260809_0037`.

## Trabajo en curso

- Implementación y automatización están cerradas; falta únicamente registrar commits/push y entregar el reporte de QA.
- El índice de contexto sigue en `docs/DOCUMENTATION_INDEX.md`; el contrato AI está en `docs/AI_FOUNDATION.md`.

## Pruebas relevantes

- MariaDB 11.4 efímera: base vacía→0038, downgrade 0038→0037, upgrade 0037→0038, `db current` y `db check`.
- Suite AI con gates MariaDB: 47 passed, incluyendo concurrencia, owner isolation y cascadas.
- Suite local AI + portabilidad: 70 passed; los skips corresponden a gates reservados a contenedor.
- Suite backend completa con fixtures QA: 792 passed, 12 skipped.
- Tests cloud no usan Internet ni una API key real.

## Bloqueadores y riesgos

- No hay bloqueadores funcionales conocidos para QA manual.
- Attachments/food vision continúan deshabilitados: no se amplió scope sin storage privado completo.
- `workout_entry` y `steps_entry` no se confirman todavía.
- No hay coach, diagnóstico, Strava, BLE, billing, cambios Android, merge, tag ni deploy.

## Siguiente paso

- QA manual del flujo `/ai`: consentimiento remoto con configuración de entorno de QA, follow-ups, evidencia, confirmación/rechazo de peso/comida y portabilidad.
- Mantener cualquier habilitación cloud de producción detrás de revisión operativa de proveedor, modelo, retención y secrets.
