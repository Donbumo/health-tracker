from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    AIIntent,
    MetricDefinition,
    ReadCapability,
)
from app.services.ai.capabilities.domains.nutrition_actions import FOOD_CREATE


METRICS = (
    MetricDefinition("calories", "Calorías", "kcal", ("sum", "average"), True, True, True, 0, "unknown_not_zero"),
    MetricDefinition("protein", "Proteína", "g", ("sum", "average"), True, True, True, 1, "unknown_not_zero"),
    MetricDefinition("fat", "Grasa", "g", ("sum", "average"), True, True, True, 1, "unknown_not_zero"),
    MetricDefinition("net_carbs", "Carbohidratos netos", "g", ("sum", "average"), True, True, True, 1, "distinct_from_total_carbs"),
    MetricDefinition("total_carbs", "Carbohidratos totales", "g", ("sum", "average"), True, True, True, 1, "distinct_from_net_carbs"),
    MetricDefinition("fiber", "Fibra", "g", ("sum", "average"), True, True, True, 1, "unknown_not_zero"),
    MetricDefinition("sugar", "Azúcar", "g", ("sum", "average"), True, True, False, 1, "unknown_not_zero"),
    MetricDefinition("sodium", "Sodio", "mg", ("sum", "average"), True, True, False, 0, "unknown_not_zero"),
    MetricDefinition("food_entries", "Alimentos registrados", "records", ("count",), True, True, False, 0, "no_record_is_not_zero_intake"),
)

MANIFEST = AICapabilityManifest(
    domain_id="nutrition",
    label="Nutrición",
    description="Ingesta, macronutrientes, cobertura y patrones registrados.",
    entities=("food_entry", "daily_nutrition"),
    metrics=METRICS,
    read_capabilities=(
        ReadCapability(AIIntent.SUMMARY, ("get_nutrition_summary",), tuple(item.id for item in METRICS)),
        ReadCapability(AIIntent.TREND, ("get_nutrition_summary",), tuple(item.id for item in METRICS[:-1]), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.COMPARE, ("get_nutrition_summary", "get_goals_summary"), tuple(item.id for item in METRICS[:-1]), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.CONSISTENCY, ("get_nutrition_summary",), tuple(item.id for item in METRICS), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.COVERAGE, ("get_nutrition_summary", "get_data_sources_summary"), tuple(item.id for item in METRICS)),
        ReadCapability(AIIntent.PATTERNS, ("get_food_patterns",), ("food_entries",), ("7d", "30d", "90d"), 1),
        ReadCapability(AIIntent.SOURCES, ("get_data_sources_summary",), tuple(item.id for item in METRICS)),
    ),
    action_capabilities=(FOOD_CREATE,),
    comparisons=True,
)
