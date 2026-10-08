# AI Coach · Proactive Coach 1.0

## Flujo y límites

`DashboardSummaryService` y `StrengthReader` (que reutiliza `GymProgressionEngine`)
→ `CoachSignalEngine` determinístico
→ `CoachBrief` de hoy y de los últimos 7 días
→ explicación AI opcional por `get_coach_brief`
→ propuesta Operator por `training.progression.update`
→ `AIActionDraft` y preview
→ confirmación explícita mediante el publicador oficial de Gym.

Las señales y el ranking son del servidor. El proveedor solo redacta una explicación a partir del brief; no decide medidas básicas, no publica revisiones y no cambia reglas de progresión. Sin proveedor o tras error/timeout, las tarjetas y su evidencia siguen disponibles. La configuración de `openrouter/free`, timeouts y retries no cambia.

## Contrato de lectura

`CoachBrief` contiene `period`, `generated_at`, `signals`, `top_priorities`, `coverage`, `domains` y `possible_actions`. Cada señal incluye `signal_id`, `domain`, `type`, `severity`, `period`, `metric`, `current`, `baseline`, `change`, `unit`, `coverage`, `provenance`, `evidence[]`, título, mensaje y acción opcional. Una señal sin evidencia estructurada se rechaza. `top_priorities` muestra hasta cinco señales, deduplicadas y ordenadas por severidad, acción disponible, cobertura y magnitud comparable.

Los briefs se generan al abrir `/today`, `/dashboard` y `/ai`; no se persisten ni se notifican. El servicio carga una vez el resumen longitudinal owner-only y una vez el snapshot owner-only de Gym. `/dashboard` reutiliza su resumen de siete días cuando coincide exactamente con el rango local del Coach. El volumen de Gym se calcula para **las mismas fechas locales** que el Dashboard, y solo se compara si sesiones, identidades y modos de carga son compatibles. El cruce Gym/nutrición requiere además al menos cinco de siete días registrados en **ambas** ventanas de ingesta. El lenguaje describe registros, no ingesta real no registrada ni causalidad.

Los umbrales v1 son deliberadamente conservadores: cinco días por ventana para tendencias de energía, pasos y gasto activo; tres mediciones para estabilidad/cambio de peso; cambios aproximados de 10 % en energía, 15 % en pasos/gasto activo y 5 % en volumen Gym; al menos dos entrenamientos planeados sin marca de completado antes de sugerir revisión. Una ausencia se conserva como ausencia, nunca como cero consumo. Los objetivos solo se comparan cuando existe cobertura suficiente. Ninguna señal es un diagnóstico médico.

Los intents `daily_coach`, `weekly_coach`, `explain_signal`, `explain_progression`, `what_changed` y `what_should_i_review` usan el registro de capabilities y la herramienta `get_coach_brief`. Para estos intents, el servidor ejecuta la lectura antes de llamar al proveedor. Una explicación de señal seleccionada solo puede consultar un `signal_id` que vuelva a existir en el brief del usuario efectivo. El proveedor remoto mantiene la compuerta de consentimiento existente. La herramienta no acepta `user_id` del cliente.

## Operator

La acción registrada `training.progression.update` es contextual: el CTA aparece únicamente ante una evaluación `increase_load` con cambios aplicables. `Preparar cambio` exige POST y CSRF, vuelve a evaluar la prescripción owner-only y crea una conversación con `AIPlanSpec` y `AIActionDraft` **sin modificar Gym**. El preview muestra carga actual, propuesta y evidencia. La confirmación verifica de nuevo propietario, revisión, propuesta y evidencia; utiliza `gym_progression_confirm.preview/confirm`, que revalida la fuente, bloquea y publica mediante el servicio oficial. Una evidencia obsoleta falla y requiere preparar otra propuesta. La segunda confirmación del mismo draft es idempotente. No se exponen hashes ni tokens de progresión en el borrador o los logs.

Las demás acciones de comida, cuerpo y metas conservan sus capabilities y su confirmación existentes. Coach no añade una ruta de escritura para ellas. La acción de progresión no aparece como acción genérica porque necesita contexto de un ejercicio evaluado.

## UX y observabilidad

La portada `/ai` abre con Hoy, Esta semana y Para revisar; el catálogo y el chat existentes continúan debajo. Las tarjetas abren “¿Por qué?” con valor, comparación, fechas, cobertura y procedencia. Gym enlaza discretamente a la explicación de su propia evaluación. Los enlaces AI preparan texto, sin enviarlo hasta que la persona pulse Enviar. Los logs de Coach registran IDs de señales, dominios, estado de cobertura y duración; nunca valores crudos, prompts ni payloads de salud. Las páginas owner-only usan `private, no-store` y controles responsivos.

No hay cambios de esquema ni migración. No se introducen notificaciones, cron, Celery, Redis ni nuevas reglas de progresión.

## Gate QA

Usar solo cuentas y series ficticias. Verificar señales con datos vacíos, parciales y suficientes; priorización/deduplicación; propiedad entre usuarios; read tool con FakeProvider; provider indisponible; CSRF; draft sin escritura, confirmación, idempotencia y evidencia obsoleta; MariaDB aislada con READ COMMITTED y REPEATABLE READ; responsive 360/390/430/768/1024/1366, tema claro/oscuro y consola. Medir consultas y tiempos del brief en historiales pequeño y grande. Nunca usar la cuenta ni datos personales como fixture.

Medición local aislada del 2026-10-06, MariaDB loopback QA, ambas vistas de brief calculadas en la misma llamada: 5 ejercicios/4 sesiones = 18 consultas y 36.7 ms; 40/4 = 18 consultas y 55.6 ms; 40/200 = 33 consultas y 1,554.8 ms. El aumento del caso grande procede de lotes de relaciones; no hay una consulta por ejercicio. Son tiempos de QA local, no un SLO de producción. `scripts/ai/coach_perf_qa.py` reproduce la medición y limpia los usuarios ficticios.
