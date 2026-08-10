# AI Foundation · Beta 1.1

Health Tracker AI es una interfaz segura sobre datos y servicios existentes, no un chatbot con acceso general al sistema.

## Habilitación

La aplicación arranca con AI desactivada. Valores de ejemplo:

```text
AI_ENABLED=false
AI_PROVIDER=fake
AI_MODEL=fake-health-v1
AI_MAX_INPUT_CHARS=4000
AI_MAX_HISTORY_MESSAGES=20
AI_MAX_TOOL_CALLS=6
AI_MAX_TOOL_ROUNDS=3
AI_PROVIDER_TIMEOUT_SECONDS=20
```

`AI_ENABLED=false`, provider ausente o modelo ausente no afectan `/health` ni el resto del producto. La web muestra `disabled`/`unconfigured` y permite consultar o eliminar historial previo. El provider `fake` es determinista, no usa red y existe para QA/demo; no debe confundirse con un modelo clínico ni con un provider cloud.

Credenciales de futuros adapters viven solo en secrets/env. No se guardan en DB, no se exponen al frontend y no deben aparecer en logs. Beta 1.1 no incluye un adapter cloud ni requiere Internet.

## Arquitectura

```text
web session o API Bearer
  → AIConversationService
  → AIProvider (interfaz estable)
  → AIToolRegistry / validación
  → services y read models existentes
  → modelos owner-only / MariaDB
```

El historial persistido contiene mensajes, tool utilizado, argumentos validados/sanitizados, resultado resumido, evidencia, errores seguros y uso técnico disponible. No se persiste chain-of-thought.

Los límites por turno cubren caracteres de entrada, mensajes de historial, rondas/cantidad de tools, longitud de respuesta y deadline entregado al adapter. Un adapter remoto debe respetar `timeout_seconds` en su propia llamada de red; el servicio rechaza además respuestas que excedan el tiempo configurado.

## Tools disponibles

- `get_dashboard_summary`
- `get_weight_trend`
- `get_nutrition_summary`
- `get_training_summary`
- `get_training_history`
- `get_activity_summary`
- `get_steps_summary`
- `get_goals_summary`
- `get_data_sources_summary`

Cada tool recibe el `User` efectivo desde sesión/Bearer. Sus schemas prohíben propiedades adicionales, incluido `user_id`. El registry no contiene SQL, filesystem, shell, browser, URLs arbitrarias ni datos médicos. Los resultados son payloads pequeños con `period`, `metrics`, `coverage`, `sources` y, cuando aplica, puntos recientes. ORM, raw payloads, rutas internas y archivos no salen de la capa server-side.

Los pasos usan la selección efectiva ya existente; una fuente manual no se suma silenciosamente a Health Connect si podrían solaparse.

## Evidencia y procedencia

Las respuestas conservan evidencia estructurada con métrica, periodo, fuente, categoría y tipo:

- `recorded`: captura manual u otro dato registrado;
- `imported`: Health Connect, device sync, import o proveedor externo;
- `calculated`: agregado determinista de Health Tracker;
- `ai_interpretation`: texto producido por el provider a partir de evidencia.

Las categorías de fuente contemplan `manual`, `health_connect`, `import`, `device`, `external_provider` y `other`. No se asume que pasos significa Health Connect.

Campos importados o externos se acotan y se envían al provider dentro de un envelope `untrusted_data`. La instrucción de sistema los declara DATA, no instrucciones; la selección de tools permanece en allowlist server-side.

## Conversaciones y superficies

La web vive en `/ai` y usa Flask-Login + CSRF. API v1 usa Bearer exclusivamente:

```text
GET    /api/v1/ai/status
POST   /api/v1/ai/conversations
GET    /api/v1/ai/conversations
GET    /api/v1/ai/conversations/<uuid>
DELETE /api/v1/ai/conversations/<uuid>
POST   /api/v1/ai/conversations/<uuid>/messages
POST   /api/v1/ai/conversations/<uuid>/retry
```

Recursos ajenos responden 404. El delete de conversación elimina mensajes, tool audit y drafts por cascade. Account deletion elimina conversaciones por FK `ON DELETE CASCADE`.

Las conversaciones AI no forman parte de `user_data_export` ni `health-tracker-portable-v1` en esta revisión: esos son contratos públicos versionados y no deben ampliarse sin schema, import, round-trip y política de merge. Esta exclusión es explícita, no impide borrado, y debe revisarse antes de Beta 1.1 final.

## Drafts y escritura

`AIActionDraft` contempla:

- `food_entry`
- `body_measurement`
- `workout_entry`
- `steps_entry`

El fake provider implementa una primera interpretación de `Peso 82.4 kg` a `body_measurement`. El estado es siempre `pending_confirmation`. No existe endpoint de confirmación en esta fase y el chat no llama a servicios de escritura.

Flujo futuro obligatorio:

```text
mensaje → interpretación → draft → preview → confirmación explícita
        → servicio oficial del dominio → DB
```

## Imágenes e importación asistida

El modelo de mensaje conserva un campo de attachments, pero la API rechaza adjuntos no vacíos con `attachments_not_supported`. No se guarda una foto ni se estima comida hasta disponer de upload privado owner-only, límites, preview y borrado. Una futura imagen de comida producirá `FoodEntryDraft` marcado `estimated_by_ai`; nunca una medición exacta ni escritura automática.

La importación asistida futura debe reutilizar:

```text
imagen/PDF/texto/CSV/JSON
  → adapter AI read-only
  → JSON canónico existente
  → schema oficial
  → preview del Import Hub
  → confirmación owner-bound
  → importador oficial
```

No se creará un segundo importador. Los generadores AI no inventan requeridos, no escriben DB/archivos y mantienen aliases fuera del contrato canónico.

## Añadir un provider

1. Implementar `AIProvider.respond(AIProviderRequest)` en un módulo adapter.
2. Traducir mensajes/tools/results sin importar SDKs en servicios de Health Tracker.
3. Respetar el timeout recibido y devolver `AIProviderResponse` provider-neutral.
4. Leer credenciales solo desde env/secrets y sanear errores/logs.
5. Agregar factory/config, fake tests, fallo/timeout, tool loop y prueba de que no requiere red.

## Añadir un tool

1. Reutilizar un service/read model owner-only; no consultar un owner pedido por el modelo.
2. Definir schema cerrado con rangos y `additionalProperties: false`.
3. Devolver estructura pequeña, distinguir null de cero e incluir cobertura/fuente.
4. Tratar texto importado/externo como datos no confiables.
5. Probar aislamiento entre dos usuarios, timezone, argumentos inválidos, ausencia de datos y procedencia.

## Datos enviados a un provider remoto futuro

Solo se enviarían el historial acotado seleccionado para el turno, la pregunta del usuario, definiciones de tools y resultados estructurados/saneados necesarios. No se envían contraseñas, tokens, secrets, `user_id` interno, ORM, SQL, paths, archivos completos, raw payloads o datos de otros usuarios. Un adapter remoto debe documentar proveedor, región/retención aplicable y consentimiento operativo antes de habilitarse.
