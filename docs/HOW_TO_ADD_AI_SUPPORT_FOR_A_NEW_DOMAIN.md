# Cómo añadir soporte AI para un dominio nuevo

El motor adaptativo genera experiencias desde capacidades tipadas. Un dominio
nuevo no requiere crear templates para resumen, tendencia, comparación y cada
periodo; requiere un read model seguro, una tool allowlisted y un manifest.

## 1. Partir de un read model owner-only

La función debe recibir el `user_id` efectivo del servidor. Nunca lo acepta en
argumentos del browser o del proveedor. Devuelve solo agregados y puntos
acotados, con cobertura, ausencia explícita y procedencia; no devuelve ORM,
payloads crudos, rutas internas ni IDs que el proveedor no necesite.

Antes de exponer una métrica define:

- unidad y precisión de display;
- agregaciones técnicamente válidas;
- si admite tendencia, comparación o metas;
- qué significa un dato ausente;
- qué fuentes/unidades son comparables.

## 2. Registrar una tool con metadata

Añade una única tool por read model coherente en
`backend/app/services/ai/tools.py`. El JSON Schema debe tener
`additionalProperties: false`, enums/rangos acotados y nunca `user_id`.
Declara `AIToolCapabilityMetadata` con dominios, entidades, métricas y
operaciones reales. El handler deriva el owner del objeto `User` autenticado.

No crees una tool por prompt. Si una tool intenta ampliar el dominio u operación
del manifest, la validación de arranque debe fallar.

## 3. Declarar el manifest

Crea un módulo en
`backend/app/services/ai/capabilities/domains/` y agrégalo a
`domains/__init__.py`. Ejemplo reducido de Sueño:

```python
MANIFEST = AICapabilityManifest(
    domain_id="sleep",
    label="Sueño",
    description="Sueño registrado por fuentes compatibles.",
    entities=("sleep_session",),
    metrics=(
        MetricDefinition(
            "sleep_duration", "Duración", "minutes", ("average", "sum"),
            comparison_supported=True,
            trend_supported=True,
            missing_data_semantics="unknown_not_zero",
        ),
    ),
    read_capabilities=(
        ReadCapability(
            AIIntent.SUMMARY,
            ("get_sleep_summary",),
            ("sleep_duration",),
        ),
        ReadCapability(
            AIIntent.TREND,
            ("get_sleep_summary",),
            ("sleep_duration",),
            ("7d", "30d", "90d"),
            minimum_records=2,
        ),
    ),
    comparisons=True,
)
```

El `AdaptiveTemplateComposer` producirá las experiencias pertinentes. Solo añade
un `AIPreset` cuando exista un ID legacy o un deep link estable que deba
conservarse; no lo uses para poblar el catálogo normal.

## 4. Disponibilidad y recomendaciones

Amplía `AICapabilityAvailabilityService` con un conteo agregado owner-only y de
coste constante. “Soportado” significa que manifest, tool y read model existen;
“sin datos” o “datos insuficientes” describe únicamente la cuenta actual. No
ocultes una capacidad real por falta de datos y no presentes una capacidad
incompleta como disponible.

Las recomendaciones son reglas determinísticas sobre metadata y conteos. No
deben consultar al proveedor ni incluir cifras de salud en links o logs.

## 5. Acciones, si existen

Declara `ActionCapability` solo cuando haya:

- draft tipado y editable;
- preview owner-bound;
- servicio oficial de dominio;
- confirmación explícita;
- idempotencia y pruebas de aislamiento.

El modelo prepara el draft; nunca escribe directamente. Si falta cualquiera de
esas piezas, conserva la metadata como foundation `available=False` con un
blocker concreto y no la registres como capacidad ejecutable.

## 6. Pruebas mínimas

Añade cobertura para:

1. validación manifest ↔ metadata de tool;
2. combinaciones válidas e inválidas de `AIIntentSpec`;
3. plan exacto de tools y rechazo de ampliación;
4. aislamiento entre dos usuarios y procedencia;
5. ausencia, cobertura y unidades incompatibles;
6. generación automática de experiencias sin templates nuevos;
7. render responsive/teclado y preparación sin autoenvío;
8. logs sin preguntas, argumentos ni valores de salud.

Usa fixtures claramente ficticias. Las pruebas de provider real se ejecutan
solo después de la suite determinística y nunca con datos personales.
