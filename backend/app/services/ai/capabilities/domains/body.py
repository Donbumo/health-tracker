from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    AIIntent,
    MetricDefinition,
    ReadCapability,
)
from app.services.ai.capabilities.domains.body_actions import BODY_CORRECT, BODY_CREATE


METRICS = (
    MetricDefinition("weight", "Peso", "user_weight_unit", ("latest", "average", "min", "max"), True, True, False, 1, "unknown_not_zero"),
    MetricDefinition("body_fat", "Grasa corporal", "%", ("latest", "average"), True, True, False, 1, "unknown_not_zero"),
    MetricDefinition("muscle_mass", "Masa muscular", "kg", ("latest", "average"), True, True, False, 1, "not_lean_mass"),
    MetricDefinition("body_water", "Agua corporal", "%", ("latest", "average"), True, True, False, 1, "percentage_only"),
    MetricDefinition("visceral_fat", "Grasa visceral", "index", ("latest", "average"), True, True, False, 1, "device_reported"),
    MetricDefinition("bmi", "IMC", "kg/m2", ("latest", "average"), True, True, False, 1, "descriptive_not_diagnostic"),
    MetricDefinition("bmr", "BMR", "kcal/day", ("latest", "average"), True, True, False, 0, "device_or_source_reported"),
)

MANIFEST = AICapabilityManifest(
    domain_id="body",
    label="Cuerpo",
    description="Peso y composición corporal reportada por las fuentes disponibles.",
    entities=("body_measurement",),
    metrics=METRICS,
    read_capabilities=(
        ReadCapability(AIIntent.SUMMARY, ("get_weight_trend", "get_latest_body_measurement"), tuple(item.id for item in METRICS)),
        ReadCapability(AIIntent.LATEST, ("get_latest_body_measurement",), tuple(item.id for item in METRICS), minimum_records=1),
        ReadCapability(AIIntent.TREND, ("get_weight_trend",), tuple(item.id for item in METRICS), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.COMPARE, ("get_weight_trend",), tuple(item.id for item in METRICS), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.COVERAGE, ("get_weight_trend",), tuple(item.id for item in METRICS)),
    ),
    action_capabilities=(BODY_CREATE, BODY_CORRECT),
    comparisons=True,
)
