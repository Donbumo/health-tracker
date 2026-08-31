from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    ActionCapability,
    AIIntent,
    MetricDefinition,
    ReadCapability,
)


METRICS = (
    MetricDefinition("adherence", "Adherencia", "%", ("average",), True, True, False, 1, "only_against_configured_goals"),
    MetricDefinition("goals", "Metas configuradas", "goals", ("count",), True, True, False, 0, "no_goal_is_not_failure"),
)

GOAL_ACTION_FOUNDATION = ActionCapability(
    "propose_goal_change",
    "goals",
    "user_goal",
    ("goal_type", "target_value", "unit", "cadence", "start_date", "end_date"),
    "goal_entry",
    True,
    "create_goal_or_patch_goal",
    available=False,
    blocker="AIActionDraft no admite goal_entry y falta un preview owner-bound específico.",
)

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
    ),
    comparisons=True,
)
