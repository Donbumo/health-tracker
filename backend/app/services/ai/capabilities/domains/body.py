from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    ActionCapability,
    AIIntent,
    MetricDefinition,
    ReadCapability,
)


METRICS = (
    MetricDefinition("weight", "Peso", "user_weight_unit", ("latest", "average", "min", "max"), True, True, False, 1, "unknown_not_zero"),
    MetricDefinition("body_fat", "Grasa corporal", "%", ("latest", "average"), True, True, False, 1, "unknown_not_zero"),
    MetricDefinition("muscle_mass", "Masa muscular", "kg", ("latest", "average"), True, True, False, 1, "not_lean_mass"),
    MetricDefinition("body_water", "Agua corporal", "%", ("latest", "average"), True, True, False, 1, "percentage_only"),
    MetricDefinition("visceral_fat", "Grasa visceral", "index", ("latest", "average"), True, True, False, 1, "device_reported"),
    MetricDefinition("bmi", "IMC", "kg/m2", ("latest", "average"), True, True, False, 1, "descriptive_not_diagnostic"),
    MetricDefinition("bmr", "BMR", "kcal/day", ("latest", "average"), True, True, False, 0, "device_or_source_reported"),
)

BODY_FIELDS = (
    "weight", "unit", "recorded_at", "body_fat_percent", "muscle_mass_kg",
    "water_percent", "visceral_fat", "bmr_kcal", "bmi", "notes",
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
    action_capabilities=(
        ActionCapability("record_measurement", "body", "body_measurement", BODY_FIELDS, "body_measurement", True, "create_body_stat"),
        ActionCapability(
            "correct_measurement",
            "body",
            "body_measurement",
            BODY_FIELDS,
            "body_measurement",
            True,
            "patch_body_stat",
            read_tools=("get_latest_body_measurement",),
        ),
    ),
    comparisons=True,
)
