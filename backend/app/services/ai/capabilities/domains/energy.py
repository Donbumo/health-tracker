from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    AIIntent,
    MetricDefinition,
    ReadCapability,
)


METRICS = (
    MetricDefinition("balance", "Balance energético", "kcal", ("sum", "average"), True, True, False, 0, "requires_intake_and_expenditure"),
    MetricDefinition("intake", "Consumo", "kcal", ("sum", "average"), True, True, True, 0, "unknown_not_zero"),
    MetricDefinition("expenditure", "Gasto", "kcal", ("sum", "average"), True, True, True, 0, "unknown_not_zero"),
)

MANIFEST = AICapabilityManifest(
    domain_id="energy",
    label="Energía",
    description="Consumo, gasto y balance únicamente en días comparables.",
    entities=("daily_nutrition", "daily_energy"),
    metrics=METRICS,
    read_capabilities=(
        ReadCapability(AIIntent.SUMMARY, ("get_dashboard_summary",), tuple(item.id for item in METRICS)),
        ReadCapability(AIIntent.TREND, ("get_dashboard_summary",), tuple(item.id for item in METRICS), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.COMPARE, ("get_dashboard_summary",), tuple(item.id for item in METRICS), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.COVERAGE, ("get_dashboard_summary",), tuple(item.id for item in METRICS)),
    ),
    comparisons=True,
)
