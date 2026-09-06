from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    AIIntent,
    MetricDefinition,
    ReadCapability,
)


METRICS = (
    MetricDefinition("activity", "Actividad", "records", ("count",), True, True, False, 0, "missing_is_unknown"),
    MetricDefinition("steps", "Pasos", "steps", ("sum", "average"), True, True, True, 0, "do_not_sum_overlapping_sources"),
    MetricDefinition("active_days", "Días con actividad", "days", ("count",), True, True, True, 0, "no_data_is_not_inactive"),
)

MANIFEST = AICapabilityManifest(
    domain_id="activity",
    label="Actividad",
    description="Actividad registrada y pasos efectivos sin duplicar fuentes.",
    entities=("activity", "daily_steps"),
    metrics=METRICS,
    read_capabilities=(
        ReadCapability(AIIntent.SUMMARY, ("get_activity_summary", "get_steps_summary"), tuple(item.id for item in METRICS)),
        ReadCapability(AIIntent.TREND, ("get_steps_summary",), ("steps", "active_days"), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.PROGRESS, ("get_steps_summary",), ("steps", "active_days"), minimum_records=1),
        ReadCapability(AIIntent.CONSISTENCY, ("get_activity_summary", "get_steps_summary"), tuple(item.id for item in METRICS), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.COVERAGE, ("get_steps_summary",), tuple(item.id for item in METRICS)),
        ReadCapability(AIIntent.SOURCES, ("get_data_sources_summary",), tuple(item.id for item in METRICS)),
    ),
    comparisons=True,
)
