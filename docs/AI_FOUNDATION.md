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
  → AIIntentSpec o propuesta estructurada validada
  → AICapabilityRegistry / AIPlanSpec
  → AIProvider
  → lecturas allowlisted, si son necesarias
  → AIActionDrafts agrupados por plan
  → confirmación explícita
  → services/read models owner-only del dominio
  → MariaDB
```

Los dominios declaran un `AICapabilityManifest` tipado con entidades, métricas,
semántica de ausencia, agregaciones, comparaciones, periodos, lecturas y acciones.
El catálogo visual y los prompts se componen desde esa metadata; no existe una
plantilla estática por cada combinación. Los 41 IDs de AI Templates 2.0 se
conservan como presets compatibles sobre el mismo motor.

La URL estructurada admite únicamente `intent`, `domain`, `metric`, `period`,
`comparison`, `action` y opciones enumeradas. No contiene cifras de salud. El
resolver valida la combinación y calcula las tools exactas antes de inicializar
el provider. Una tool que el modelo solicite fuera del plan se rechaza aunque
pertenezca al registro global.

El contexto se selecciona desde lo más reciente de forma determinista con `AI_MAX_HISTORY_MESSAGES`, `AI_MAX_HISTORY_CHARS` y `AI_MAX_HISTORY_TURNS`. Cada turno limita rondas/tools, output y usage total reportado. No se almacena chain-of-thought. Solo se guardan mensaje, modelo/provider, input/output tokens, auditoría reducida y evidencia.

La política temporal por defecto es coherente y estricta: llamada individual al provider 20 s < turno AI completo 50 s < worker Gunicorn 60 s. El transporte HTTP usa el timeout de la llamada; no hay timeout adicional en el JavaScript de `/ai`, no existe configuración de reverse proxy en este repositorio y el retry HTTP no es automático. Cada turno limita el timeout de su siguiente llamada al presupuesto total restante. El retry manual reutiliza el último mensaje de usuario sin respuesta; no confirma drafts, no crea registros por sí solo y conserva las claves idempotentes del draft que finalmente se revise.

Errores de timeout, deadline total, autenticación, quota/rate limit, modelo ausente, respuesta/tool call malformada y proveedor offline se convierten a códigos y mensajes seguros. El cuerpo crudo del provider y sus credenciales no se registran. El mensaje del usuario queda disponible para retry.

Cada request AI emite un evento sanitizado `ai_turn_timing` con `intent`,
`domain`, IDs de métricas, periodo, `total_ms`, rondas y milisegundos de
provider, número/nombre/duración de tools, tiempo total de read models y outcome
(`success`, `provider_timeout`, `overall_deadline`, `tool_error`,
`provider_error` o `round_limit`). El catálogo registra solo tiempos de
composición/resolución. Ningún evento incluye prompt, argumentos, resultados,
API keys ni payloads de salud.

## Tools read-only

- `get_dashboard_summary`
- `get_latest_body_measurement`
- `get_weight_trend`
- `get_nutrition_summary`
- `get_food_patterns`
- `get_training_summary`
- `get_training_history`
- `get_exercise_progress`
- `get_activity_summary`
- `get_steps_summary`
- `get_goals_summary`
- `get_data_sources_summary`

`get_latest_body_measurement` consulta la última medición sin ventana temporal, la última hasta una fecha o la medición de una fecha local exacta; devuelve peso, grasa corporal, masa muscular, agua corporal, grasa visceral, BMR e IMC cuando existen. `get_weight_trend` permanece reservado para cambios, promedios y periodos.

`get_food_patterns` describe frecuencia de días, distribución por tipo de
comida, elementos repetidos, consistencia de métricas, cobertura y procedencia.
El modelo actual no guarda hora separada de comida y la tool lo declara como no
disponible; no infiere causalidad ni calidad clínica. `get_exercise_progress`
reutiliza el read model móvil owner-only y solo publica carga, volumen y mejores
marcas cuando el modo de carga es comparable; elimina IDs internos y no suma
modos incompatibles.

Los schemas son cerrados y nunca aceptan owner del modelo. No existen tools de SQL, shell, filesystem, browser, URL o medicina. Los payloads exponen `period`, `metrics`, `coverage`, fuentes y solo los puntos recientes necesarios. Null sigue significando ausencia, no cero.

Una response puede solicitar varias tools independientes y el servicio devuelve todos los resultados en una sola ronda de follow-up. Se ejecutan secuencialmente porque comparten la sesión owner-only de SQLAlchemy; no se paralelizan hasta contar con mediciones reales que justifiquen separar sesiones/transacciones. Para resúmenes multi-dominio se prioriza `get_dashboard_summary` en vez de una secuencia de tools o un mega-dump.

Todo texto importado, notas y procedencia externa cruza la frontera como `untrusted_data`: es DATA, nunca instrucciones. La procedencia de futuras integraciones se representa como `source_type=external_provider`, `provider` y `resource_type`; AI no conoce endpoints del proveedor externo.

## Conversaciones, evidencia y borrado

La web vive en `/ai` con Flask-Login/CSRF. API v1 usa Bearer y UUID públicos. Recursos de otro owner responden 404. La evidencia visible resume periodo, cobertura y fuentes principales sin tool arguments de debug.

El delete de conversación es hard delete y elimina mensajes, tool audit y drafts; no revierte recursos de salud que el usuario ya confirmó. El delete de cuenta elimina toda la jerarquía AI por FK `ON DELETE CASCADE`.

## Operator, planes y confirmación

`ActionCapability` es el contrato estable, provider-neutral y propiedad de cada
dominio. Declara `action_id`, dominio, entidad, operación, campos soportados,
schema cerrado, lecturas previas, resolución owner-only, preview, handler del
servicio oficial, confirmación e idempotencia. El proveedor recibe únicamente
la definición declarativa: nunca selecciona una función Python, un nombre de
servicio o un ID de usuario.

Las siete acciones disponibles son `nutrition.food.create`,
`body.measurement.create`, `body.measurement.correct`,
`training.session.create`, `training.session.correct`, `goal.create` y
`goal.update`. Entrenamiento exige una versión y día reales del plan; si no se
pueden resolver queda `needs_input`. Crear o modificar metas sólo admite tipos
ya soportados por el servicio de objetivos.

Una propuesta del provider cruza un parser estricto y se convierte en
`AIPlanSpec`: `plan_id`, intención, resumen y uno o más pasos con capability,
dominio, entidad, operación, argumentos, dependencias y estado. Acciones
desconocidas, campos adicionales, operaciones incompatibles, ciclos y recursos
fuera del owner se rechazan en servidor. Los estados lógicos son `proposed`,
`needs_input`, `ready`, `confirmed`, `rejected`, `applied` y `failed`.

Cada paso se persiste en un `AIActionDraft` existente. `provenance_json`
mantiene la identidad del plan, orden/dependencias, capability, estado y
contexto owner-bound; no existe una segunda tabla de workflows. Los estados de
persistencia continúan siendo `pending_confirmation`, `applied`, `rejected`,
`expired` y `failed`.

```text
mensaje → lecturas necesarias → plan validado → drafts → preview editable
        → confirmación explícita por paso o del plan
        → services oficiales del dominio → recursos → applied
```

Peso reutiliza `create_body_stat` y las correcciones explícitas reutilizan
`patch_body_stat`; comida reutiliza `create_nutrition_item`; entrenamiento usa
los servicios de sesión y corrección vinculados a la versión inmutable del
plan; metas usa `create_goal`/`patch_goal`. El modelo nunca escribe. Los campos
desconocidos permanecen ausentes o null con warnings/missing fields: no se
inventan valores para completar el schema.

Una continuación marcada como corrección o ampliación reemplaza de forma owner-only el contenido del draft pendiente en vez de crear silenciosamente otro registro. Si el draft corporal ya fue aplicado, se crea un nuevo preview de corrección ligado a la revisión del recurso y se exige otra confirmación. Todo campo explícito soportado debe conservarse; los no soportados generan warning visible y los ambiguos bloquean confirmación hasta corregirse.

Confirmación, edición y rechazo son owner-only. Una edición simple se valida y
renderiza localmente sin llamar al provider. Confirmar todo ignora pasos ya
aplicados o rechazados y respeta dependencias; un fallo no revierte recursos ya
aplicados. El retry sólo reintenta pasos fallidos seguros. Cada confirmación
bloquea la fila y usa la idempotencia del draft/servicio, de modo que repetición
y concurrencia devuelven el resultado existente sin duplicar.

`PROPOSE_CHANGES` ejecuta primero las lecturas actuales, separa
`OBSERVACIONES` de `CAMBIOS PROPUESTOS` y produce únicamente previews. Una
continuación conversacional vuelve a consultar las tools requeridas en lugar de
tratar el texto histórico como fuente de verdad. Ninguna propuesta es una
recomendación médica ni se aplica automáticamente.

Las páginas de dominio pueden emitir un token de contexto firmado, breve y
ligado a owner/capability/recurso después de resolver el recurso en servidor.
La URL transporta el token opaco, no valores de salud. La capability vuelve a
comprobar ownership y revisión al preparar y confirmar la corrección.

Los logs de Operator contienen únicamente IDs técnicos, action IDs, estados,
conteos y timings; nunca prompts completos, argumentos, drafts ni valores de
salud. Un recurso aplicado se marca como
`ai_assisted_user_confirmed`, no como escritura autónoma.

## Portabilidad

`health-tracker-portable-v1` incluye la sección `ai_conversations` con conversaciones, mensajes, evidencia, usage técnico, metadata reducida de tools y drafts. Import hace preview, resolución owner-only y round-trip como las demás secciones.

Se omiten API keys, secretos, `provider_call_id`, argumentos internos, respuestas crudas y chain-of-thought. El consentimiento remoto no se importa: habilitar transferencia en otro entorno exige una decisión local explícita.

## Limitaciones del RC

- Attachments y food vision siguen rechazados hasta existir storage privado owner-only con lifecycle completo.
- No hay coach autónomo, diagnóstico, Strava, BLE ni acciones silenciosas.
- No se calculan costos monetarios ni billing.
- No existen acciones genéricas de delete; cada corrección es opt-in del dominio.
- Workout/steps legacy siguen sin habilitarse como drafts genéricos; la acción
  de entrenamiento disponible usa el contrato real de sesiones planificadas.
- El estado “capacidad soportada” es distinto de “el usuario tiene datos”: la
  interfaz muestra sin datos o datos insuficientes sin ocultar la capacidad.

Para extender el motor consulta
[HOW_TO_ADD_AI_SUPPORT_FOR_A_NEW_DOMAIN.md](HOW_TO_ADD_AI_SUPPORT_FOR_A_NEW_DOMAIN.md)
y [HOW_TO_ADD_AN_AI_ACTION_CAPABILITY.md](HOW_TO_ADD_AN_AI_ACTION_CAPABILITY.md).
