from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    AIIntent,
    MetricDefinition,
    ReadCapability,
)
from app.services.ai.capabilities.domains.goal_actions import GOAL_CREATE, GOAL_UPDATE


METRICS = (
    MetricDefinition("adherence", "Adherencia", "%", ("average",), True, True, False, 1, "only_against_configured_goals"),
    MetricDefinition("goals", "Metas configuradas", "goals", ("count",), True, True, False, 0, "no_goal_is_not_failure"),
)

GOAL_ACTION_FOUNDATION = GOAL_UPDATE

MANIFEST = AICapabilityManifest(
    domain_id="goals",
    label="Metas",
    description="Progreso descriptivo contra metas configuradas por el usuario.",
    entities=("user_goal",),
    metrics=METRICS,
    read_capabilities=(
        ReadCapability(AIIntent.SUMMARY, ("get_goals_summary",), tuple(item.id for item in METRICS)),
        ReadCapability(AIIntent.PROGRESS, ("get_goals_summary",), tuple(item.id for item in METRICS), ("7d", "30d", "90d"), 1),
        ReadCapability(AIIntent.COVERAGE, ("get_goals_summary",), tuple(item.id for item in METRICS)),
        ReadCapability(AIIntent.PROPOSE_CHANGES, ("get_goals_summary",), tuple(item.id for item in METRICS), ("7d", "30d", "90d")),
    ),
    action_capabilities=(GOAL_CREATE, GOAL_UPDATE),
    comparisons=True,
)
