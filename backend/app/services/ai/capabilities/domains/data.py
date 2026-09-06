from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    AIIntent,
    MetricDefinition,
    ReadCapability,
)


METRICS = (
    MetricDefinition("coverage", "Cobertura de datos", "days", ("count",), True, True, False, 0, "missing_is_explicit"),
    MetricDefinition("provenance", "Fuentes", "sources", ("count",), False, False, False, 0, "source_is_not_quality"),
)

MANIFEST = AICapabilityManifest(
    domain_id="data",
    label="Datos y fuentes",
    description="Cobertura, ausencia explícita y procedencia sin payloads crudos.",
    entities=("data_source", "coverage"),
    metrics=METRICS,
    read_capabilities=(
        ReadCapability(AIIntent.SUMMARY, ("get_data_sources_summary",), tuple(item.id for item in METRICS)),
        ReadCapability(AIIntent.COVERAGE, ("get_dashboard_summary", "get_data_sources_summary"), tuple(item.id for item in METRICS)),
        ReadCapability(AIIntent.SOURCES, ("get_data_sources_summary",), tuple(item.id for item in METRICS)),
    ),
)
