# AI Foundation · Beta 1.1 RC

Health Tracker AI es una interfaz segura sobre datos y servicios existentes. No tiene acceso general al sistema, no diagnostica y no ejecuta escrituras autónomas.

## Configuración

AI arranca desactivada. `fake` sigue siendo el provider determinista sin red para QA; `openai` es el adapter cloud real sobre Responses API.

```text
AI_ENABLED=false
AI_PROVIDER=fake
AI_MODEL=fake-health-v1
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=
AI_MAX_INPUT_CHARS=4000
AI_MAX_HISTORY_MESSAGES=20
AI_MAX_HISTORY_CHARS=16000
AI_MAX_HISTORY_TURNS=10
AI_MAX_TOOL_CALLS=6
AI_MAX_TOOL_ROUNDS=3
AI_MAX_TOTAL_TOKENS=100000
AI_MAX_OUTPUT_TOKENS=2000
AI_PROVIDER_TIMEOUT_SECONDS=20
AI_OVERALL_DEADLINE_SECONDS=50
AI_DRAFT_TTL_HOURS=168
```

Para cloud se usan `AI_PROVIDER=openai`, un modelo compatible en `AI_MODEL` y `AI_API_KEY` exclusivamente desde env/secret. `AI_BASE_URL` acepta la base HTTPS de una Responses API compatible y, si no se configura, conserva exactamente `https://api.openai.com/v1`; el adapter siempre llama a `<base>/responses`. La key nunca se guarda en DB, frontend, exports, excepciones o logs. Si falta configuración, la app y `/health` arrancan con normalidad y AI queda `disabled` o `unconfigured`.

### Perfil gratuito de QA con OpenRouter

Este perfil reutiliza `OpenAIResponsesProvider`; `AI_PROVIDER=openai` identifica el adapter existente y no introduce lógica de dominio específica de OpenRouter.

```text
AI_ENABLED=true
AI_PROVIDER=openai
AI_MODEL=openrouter/free
AI_BASE_URL=https://openrouter.ai/api/v1
AI_API_KEY=<secret de QA>
```

Se limita a desarrollo y QA manual con fixtures sintéticas: no se deben enviar datos personales o reales de salud. El router gratuito selecciona modelos disponibles dinámicamente, por lo que capacidad, latencia, disponibilidad y rate limits pueden variar y no constituyen un perfil de producción.

El adapter declara capabilities provider-neutral: tools, imágenes, structured output, usage y si es remoto. El servicio decide disponibilidad por capabilities; no contiene ramas funcionales por vendor. Las imágenes permanecen deshabilitadas.

## Consentimiento y datos enviados

Un provider remoto exige consentimiento por usuario antes de enviar el primer mensaje. `/ai` muestra provider/model, explica la transferencia y permite habilitar o deshabilitar AI remota; la API usa `GET/PUT /api/v1/ai/settings`. La preferencia se guarda sin credenciales y deshabilitarla bloquea nuevos envíos, no oculta el historial.

Por turno solo pueden salir:

- la pregunta;
- mensajes recientes seleccionados por límites de mensajes, caracteres y turnos;
- instrucciones de seguridad y schemas de tools/drafts;
- resultados mínimos de las tools necesarias.

No salen perfil completo, email, username, `user_id`, ORM, SQL, raw payloads, paths, archivos, tokens, secretos ni datos de otro owner. El adapter cloud usa `store=false`; la política operativa del proveedor desplegado sigue siendo responsabilidad del operador.

## Arquitectura y límites

```text
web session o API Bearer
  → AIConversationService
  → AIProvider
  → AIToolRegistry allowlisted
  → services/read models owner-only
  → MariaDB
```

El contexto se selecciona desde lo más reciente de forma determinista con `AI_MAX_HISTORY_MESSAGES`, `AI_MAX_HISTORY_CHARS` y `AI_MAX_HISTORY_TURNS`. Cada turno limita rondas/tools, output y usage total reportado. No se almacena chain-of-thought. Solo se guardan mensaje, modelo/provider, input/output tokens, auditoría reducida y evidencia.

La política temporal por defecto es coherente y estricta: llamada individual al provider 20 s < turno AI completo 50 s < worker Gunicorn 60 s. El transporte HTTP usa el timeout de la llamada; no hay timeout adicional en el JavaScript de `/ai`, no existe configuración de reverse proxy en este repositorio y el retry HTTP no es automático. Cada turno limita el timeout de su siguiente llamada al presupuesto total restante. El retry manual reutiliza el último mensaje de usuario sin respuesta; no confirma drafts, no crea registros por sí solo y conserva las claves idempotentes del draft que finalmente se revise.

Errores de timeout, deadline total, autenticación, quota/rate limit, modelo ausente, respuesta/tool call malformada y proveedor offline se convierten a códigos y mensajes seguros. El cuerpo crudo del provider y sus credenciales no se registran. El mensaje del usuario queda disponible para retry.

Cada request AI emite un evento sanitizado `ai_turn_timing` con `total_ms`, rondas y milisegundos de provider, número/nombre/duración de tools, tiempo total de read models y outcome (`success`, `provider_timeout`, `overall_deadline`, `tool_error`, `provider_error` o `round_limit`). No incluye prompt, argumentos, resultados, API keys ni payloads de salud.

## Tools read-only

- `get_dashboard_summary`
- `get_latest_body_measurement`
- `get_weight_trend`
- `get_nutrition_summary`
- `get_training_summary`
- `get_training_history`
- `get_activity_summary`
- `get_steps_summary`
- `get_goals_summary`
- `get_data_sources_summary`

`get_latest_body_measurement` consulta la última medición sin ventana temporal, la última hasta una fecha o la medición de una fecha local exacta; devuelve peso, grasa corporal, masa muscular, agua corporal, grasa visceral, BMR e IMC cuando existen. `get_weight_trend` permanece reservado para cambios, promedios y periodos.

Los schemas son cerrados y nunca aceptan owner del modelo. No existen tools de SQL, shell, filesystem, browser, URL o medicina. Los payloads exponen `period`, `metrics`, `coverage`, fuentes y solo los puntos recientes necesarios. Null sigue significando ausencia, no cero.

Una response puede solicitar varias tools independientes y el servicio devuelve todos los resultados en una sola ronda de follow-up. Se ejecutan secuencialmente porque comparten la sesión owner-only de SQLAlchemy; no se paralelizan hasta contar con mediciones reales que justifiquen separar sesiones/transacciones. Para resúmenes multi-dominio se prioriza `get_dashboard_summary` en vez de una secuencia de tools o un mega-dump.

Todo texto importado, notas y procedencia externa cruza la frontera como `untrusted_data`: es DATA, nunca instrucciones. La procedencia de futuras integraciones se representa como `source_type=external_provider`, `provider` y `resource_type`; AI no conoce endpoints del proveedor externo.

## Conversaciones, evidencia y borrado

La web vive en `/ai` con Flask-Login/CSRF. API v1 usa Bearer y UUID públicos. Recursos de otro owner responden 404. La evidencia visible resume periodo, cobertura y fuentes principales sin tool arguments de debug.

El delete de conversación es hard delete y elimina mensajes, tool audit y drafts; no revierte recursos de salud que el usuario ya confirmó. El delete de cuenta elimina toda la jerarquía AI por FK `ON DELETE CASCADE`.

## Drafts y confirmación

Los estados son `pending_confirmation`, `applied`, `rejected`, `expired` y `failed`. `body_measurement` y `food_entry` pueden confirmarse; `workout_entry` y `steps_entry` continúan preparados pero no habilitados.

```text
mensaje → draft → preview editable → confirmación explícita
        → service oficial del dominio → recurso → applied
```

Peso reutiliza `create_body_stat` y las correcciones explícitas de un registro ya aplicado reutilizan `patch_body_stat`; comida reutiliza `create_nutrition_item`. El modelo nunca escribe. El draft corporal conserva `weight`, unidad, fecha/hora opcional, grasa corporal, masa muscular, agua corporal, grasa visceral, BMR, IMC y notas. El draft de comida conserva calorías, proteína, grasa, carbohidratos netos y totales sin equipararlos, fibra, azúcar, sodio y notas. Los nutrientes desconocidos quedan null con warnings/missing fields, no se inventan.

Una continuación marcada como corrección o ampliación reemplaza de forma owner-only el contenido del draft pendiente en vez de crear silenciosamente otro registro. Si el draft corporal ya fue aplicado, se crea un nuevo preview de corrección ligado a la revisión del recurso y se exige otra confirmación. Todo campo explícito soportado debe conservarse; los no soportados generan warning visible y los ambiguos bloquean confirmación hasta corregirse.

Confirmación y rechazo son owner-only. La confirmación bloquea la fila, ejecuta una transacción y usa `client_event_id` determinista derivado del draft por recurso. Repeticiones y confirmaciones concurrentes devuelven el mismo resultado sin duplicar. El draft enlaza tipo e IDs públicos creados.

## Portabilidad

`health-tracker-portable-v1` incluye la sección `ai_conversations` con conversaciones, mensajes, evidencia, usage técnico, metadata reducida de tools y drafts. Import hace preview, resolución owner-only y round-trip como las demás secciones.

Se omiten API keys, secretos, `provider_call_id`, argumentos internos, respuestas crudas y chain-of-thought. El consentimiento remoto no se importa: habilitar transferencia en otro entorno exige una decisión local explícita.

## Limitaciones del RC

- Attachments y food vision siguen rechazados hasta existir storage privado owner-only con lifecycle completo.
- No hay coach autónomo, diagnóstico, Strava, BLE ni acciones silenciosas.
- No se calculan costos monetarios ni billing.
- Confirmación de workout/steps queda para una iteración posterior.
