# Cómo añadir una ActionCapability de AI

Una acción AI es un adaptador declarativo entre una intención del usuario y un
servicio oficial ya existente. El módulo de dominio posee validación, resolución
owner-only, preview y aplicación. El núcleo sólo descubre, valida y orquesta el
contrato; nunca contiene una lista de funciones Python por dominio.

## Contrato mínimo

Declara un `ActionCapability` dentro del módulo del dominio y añádelo a
`action_capabilities` de su `AICapabilityManifest`:

```python
SLEEP_LOG = ActionCapability(
    action_id="sleep.log",
    domain="sleep",
    entity="sleep_entry",
    operation="create",
    label="Registrar sueño",
    description="Prepara un registro de sueño.",
    supported_fields=("duration", "quality"),
    required_fields=("duration", "quality"),
    optional_fields=(),
    input_schema={
        "type": "object",
        "properties": {
            "duration": {"type": "number", "minimum": 0, "maximum": 24},
            "quality": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        "additionalProperties": False,
    },
    apply_handler=apply_sleep_log,
)

MANIFEST = AICapabilityManifest(
    domain_id="sleep",
    label="Sueño",
    description="Sueño registrado por fuentes compatibles.",
    entities=("sleep_entry",),
    metrics=(),
    read_capabilities=(),
    action_capabilities=(SLEEP_LOG,),
)
```

Al incorporar ese manifest al registro de módulos, la misma metadata alimenta
automáticamente el resolver, el schema enviado al provider, la forma del
composer y el bloque de acciones de `/ai`. `AIConversationService` no necesita
ramas para `sleep` ni conocer `apply_sleep_log`. El test con `sleep.log` debe
inyectar el manifest como un módulo futuro y demostrar discovery, resolve,
draft, preview y confirmación requerida sin modificar el núcleo.

## Reglas del schema y normalización

- Usa un `action_id` globalmente único y estable, con forma `dominio.entidad.acción`.
- `domain` debe coincidir con el manifest y `entity` con una entidad declarada.
- `supported_fields` debe ser exactamente la unión de required/optional y de las
  propiedades del schema.
- Mantén `additionalProperties: false`; no aceptes `user_id`, service names,
  tools, SQL, rutas, URLs ni IDs internos.
- Normaliza unidades/fechas sólo con reglas deterministas del dominio. No
  inventes valores requeridos; devuelve `needs_input` cuando falten.
- Si la acción necesita análisis actual, declara `required_read_capabilities`.
  Esas tools se ejecutan antes de exponer las definiciones de escritura.

El registro valida estas invariantes al arrancar. Una capability incompleta se
declara `available=False` con un `blocker`; no se expone como ejecutable.

## Ownership y contexto

Las acciones de creación derivan siempre el owner del `User` autenticado. Para
correcciones, implementa un `owner_resolver(user, arguments, resource_context)`
que busque por `user.id` y UUID público, capture revisión/original y responda 404
si el recurso no pertenece al owner.

Una página de dominio puede abrir AI con un token creado por
`issue_action_context_token` únicamente después de su propia consulta
owner-only. El token se liga a usuario, capability, dominio, tipo y UUID público;
expira y no contiene valores de salud. La capability debe revalidar owner y
revisión tanto al preparar el draft como al aplicar.

## Preview y aplicación

El `previewer` devuelve campos editables y, para correcciones, `original`. Una
edición se vuelve a normalizar, validar y resolver localmente; no llama al
provider. El `apply_handler` recibe argumentos ya validados y el contexto
persistido, pero aun así usa el servicio oficial owner-scoped y deja que éste
controle reglas, revisiones e idempotencia.

`confirmation_required=True`, `ownership_policy="effective_server_user"` e
`idempotency_policy="draft_uuid"` son los defaults seguros. No los relajes. La
capability devuelve sólo `ActionApplyResult(resource_type, public_ids)` y nunca
hace commit autónomo fuera del flujo coordinado.

Los recursos se marcan como `ai_assisted_user_confirmed`. El audit trail puede
guardar `plan_id`, conversation/draft IDs, action ID, estado, timestamps y UUIDs
públicos de resultado. Los logs no guardan argumentos, valores de salud,
prompts, payloads ni secretos.

## Planes, fallos e idempotencia

Cada propuesta se transforma en un `AIPlanSpec` estricto y cada paso en un
`AIActionDraft` con metadata común de plan. Dependencias deben referir pasos del
mismo plan y no formar ciclos. Confirmación individual y rechazo son siempre
posibles; confirmar todo omite pasos terminados y espera dependencias. Un fallo
queda en su paso, no revierte éxitos de otros dominios, y retry sólo intenta
fallidos seguros. Repetir o competir por la misma confirmación debe devolver el
mismo recurso, nunca duplicarlo.

No añadas deletes genéricos. Una operación destructiva futura necesita un
contrato opt-in separado, semántica de recuperación y revisión de seguridad.

## Interpretación determinística opcional

`ActionCapability.language` permite declarar `ActionLanguage` y
`ActionNumericSlot` en el módulo propietario del dominio. El intérprete
descubre esa metadata desde el registro; no importa handlers de dominios ni
contiene un switch por capability.

```python
language=(ActionLanguage(
    verbs=("registrar", "anotar"),
    entities=("sueño",),
    slots=(
        ActionNumericSlot("duration", aliases=("duración",),
                          units=(("horas", "h"),), primary=True),
        ActionNumericSlot("quality", aliases=("calidad",)),
    ),
),)
```

`Anotar sueño de 8 horas y calidad 4` produce argumentos de ese schema.
`bindings` expresa únicamente semántica de la entidad declarada, como
`goal_type` o `meal_type`. Los paths anidados pueden referir `items.0.name`.
No uses bindings para fabricar métricas requeridas o recomendar valores.
El registro rechaza paths que no existan en el schema. Las unidades son aliases
de la unidad del contrato; para múltiples unidades, declara `unit_field` y
delega compatibilidad/conversión al normalizador del dominio.

La confianza es una condición cerrada: una interpretación única de todas las
cláusulas, todos los tokens consumidos, campos y unidades reconocidos y ningún
target repetido. No se estima una probabilidad. Preguntas, negaciones,
condicionales, fechas no soportadas, valores en conflicto y texto residual
vuelven al provider; el parser nunca recomienda valores. El primer alcance
acepta comandos simples en español y declaraciones corporales explícitas,
con el periodo actual; otros periodos conservan el flujo existente.

El resultado es una propuesta neutral (`AIProviderPlanProposal`, pese a su
nombre histórico). Siempre cruza `resolve_action_proposal` y se convierte en
`AIPlanSpec` mediante schema, normalización y owner resolver. Si falta un
target o hay varios, la capability conserva `needs_input`; no cambia update
por create. Sólo se persisten conversación, auditoría de lecturas y drafts.

Las respuestas de slots usan la misma metadata sobre el plan pendiente y
conservan plan, draft, step y contexto por paso. Un fragmento con unidad puede
identificar un slot; un número sin unidad sólo se asigna cuando queda una
opción inequívoca. Unidades incompatibles se rechazan y no modifican el plan.
Los pasos aplicados, rechazados o expirados permanecen protegidos.

Los drafts determinísticos usan el mismo preview y confirmación oficial;
su provenance indica `parsed_deterministically`, sin atribuir uso a un modelo.
Los logs sólo incluyen resolución, capability IDs, conteos, IDs de campos
faltantes tomados del contrato, outcome y duración. La función AI conserva su
habilitación y consentimiento existentes; una caída del proveedor o una
factoría que falla no impide estos planes cuando la función está habilitada
y configurada. No se cambia la configuración del proveedor.

## Gates mínimos

Antes de registrar una acción real, prueba:

1. schema cerrado, campos faltantes/desconocidos y operación incompatible;
2. owner isolation, token/contexto inválido y conflicto de revisión;
3. cero writes antes de confirmación y CSRF en web;
4. preview/edición local y uso del servicio oficial;
5. reconfirmación y concurrencia idempotentes en MariaDB;
6. plan multi-step, dependencias, confirmación parcial, fallo y retry;
7. provenance/portabilidad y logs sin valores sensibles;
8. discovery automática en composer y UI responsive.

Usa sólo fixtures ficticias. Las pruebas con proveedor remoto se detienen en
preview salvo una confirmación local controlada y limpiada por el servicio
normal.
