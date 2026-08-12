# AI Foundation · Beta 1.1 RC

Health Tracker AI es una interfaz segura sobre datos y servicios existentes. No tiene acceso general al sistema, no diagnostica y no ejecuta escrituras autónomas.

## Configuración

AI arranca desactivada. `fake` sigue siendo el provider determinista sin red para QA; `openai` es el adapter cloud real sobre Responses API.

```text
AI_ENABLED=false
AI_PROVIDER=fake
AI_MODEL=fake-health-v1
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
AI_DRAFT_TTL_HOURS=168
```

Para cloud se usan `AI_PROVIDER=openai`, un modelo compatible en `AI_MODEL` y `AI_API_KEY` exclusivamente desde env/secret. La key nunca se guarda en DB, frontend, exports, excepciones o logs. Si falta configuración, la app y `/health` arrancan con normalidad y AI queda `disabled` o `unconfigured`.

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

Errores de timeout, autenticación, quota/rate limit, modelo ausente, respuesta/tool call malformada y proveedor offline se convierten a códigos y mensajes seguros. El cuerpo crudo del provider y sus credenciales no se registran. El mensaje del usuario queda disponible para retry.

## Tools read-only

- `get_dashboard_summary`
- `get_weight_trend`
- `get_nutrition_summary`
- `get_training_summary`
- `get_training_history`
- `get_activity_summary`
- `get_steps_summary`
- `get_goals_summary`
- `get_data_sources_summary`

Los schemas son cerrados y nunca aceptan owner del modelo. No existen tools de SQL, shell, filesystem, browser, URL o medicina. Los payloads exponen `period`, `metrics`, `coverage`, fuentes y solo los puntos recientes necesarios. Null sigue significando ausencia, no cero.

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

Peso reutiliza `create_body_stat`; comida reutiliza `create_nutrition_item`. El modelo nunca escribe. `Peso 82.4 kg`, `Comí 3 huevos` y cantidades en gramos generan previews con procedencia `reported_by_user` + `parsed_by_ai`. Los nutrientes desconocidos quedan null con warnings/missing fields, no se inventan.

Confirmación y rechazo son owner-only. La confirmación bloquea la fila, ejecuta una transacción y usa `client_event_id` determinista derivado del draft por recurso. Repeticiones y confirmaciones concurrentes devuelven el mismo resultado sin duplicar. El draft enlaza tipo e IDs públicos creados.

## Portabilidad

`health-tracker-portable-v1` incluye la sección `ai_conversations` con conversaciones, mensajes, evidencia, usage técnico, metadata reducida de tools y drafts. Import hace preview, resolución owner-only y round-trip como las demás secciones.

Se omiten API keys, secretos, `provider_call_id`, argumentos internos, respuestas crudas y chain-of-thought. El consentimiento remoto no se importa: habilitar transferencia en otro entorno exige una decisión local explícita.

## Limitaciones del RC

- Attachments y food vision siguen rechazados hasta existir storage privado owner-only con lifecycle completo.
- No hay coach autónomo, diagnóstico, Strava, BLE ni acciones silenciosas.
- No se calculan costos monetarios ni billing.
- Confirmación de workout/steps queda para una iteración posterior.
