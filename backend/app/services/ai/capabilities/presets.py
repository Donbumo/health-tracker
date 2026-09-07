from app.services.ai.capabilities.types import AIIntent, AIPreset


def _preset(template_id, intent, domain, metrics=(), *, action=None, options=()):
    return AIPreset(template_id, AIIntent(intent), domain, tuple(metrics), action, tuple(options))


LEGACY_PRESETS = (
    _preset("today-summary", "summary", "all"),
    _preset("weekly-summary", "summary", "all"),
    _preset("monthly-summary", "summary", "all"),
    _preset("period-summary", "summary", "all"),
    _preset("compare-periods", "compare", "all"),
    _preset("energy-balance", "summary", "energy", ("balance", "intake", "expenditure")),
    _preset("deficit-focus", "summary", "energy", ("balance",), options=(("focus", "deficit"),)),
    _preset("expenditure-trend", "trend", "energy", ("expenditure",)),
    _preset("intake-trend", "trend", "energy", ("intake",)),
    _preset("nutrition-overview", "summary", "nutrition"),
    _preset("protein-consistency", "consistency", "nutrition", ("protein",)),
    _preset("macro-goals", "compare", "nutrition", ("protein", "fat", "net_carbs"), options=(("focus", "goals"),)),
    _preset("nutrition-data-quality", "coverage", "nutrition"),
    _preset("food-patterns", "patterns", "nutrition", ("food_entries",)),
    _preset("weight-trend", "trend", "body", ("weight",)),
    _preset("body-composition", "summary", "body"),
    _preset("compare-body-period", "compare", "body", ("weight",)),
    _preset("latest-body-measurement", "latest", "body"),
    _preset("activity-overview", "summary", "activity"),
    _preset("steps-progress", "progress", "activity", ("steps",)),
    _preset("activity-consistency", "consistency", "activity", ("activity", "steps")),
    _preset("active-days", "coverage", "activity", ("active_days",)),
    _preset("training-summary", "summary", "training"),
    _preset("training-consistency", "consistency", "training", ("sessions", "duration")),
    _preset("training-volume", "compare", "training", ("volume",)),
    _preset("training-history", "latest", "training", ("sessions",), options=(("focus", "history"),)),
    _preset("exercise-progress", "progress", "training", ("exercise_load", "volume", "reps")),
    _preset("goals-overview", "summary", "goals"),
    _preset("goals-progress", "progress", "goals", ("adherence",)),
    _preset("goal-gaps", "coverage", "goals"),
    _preset("data-quality", "coverage", "data"),
    _preset("data-sources", "sources", "data"),
    _preset("what-do-you-know", "summary", "data"),
    _preset("log-food", "record", "nutrition", action="nutrition.food.create"),
    _preset("quick-breakfast", "record", "nutrition", action="nutrition.food.create", options=(("meal_type", "breakfast"),)),
    _preset("quick-lunch", "record", "nutrition", action="nutrition.food.create", options=(("meal_type", "lunch"),)),
    _preset("quick-dinner", "record", "nutrition", action="nutrition.food.create", options=(("meal_type", "dinner"),)),
    _preset("quick-snack", "record", "nutrition", action="nutrition.food.create", options=(("meal_type", "snack"),)),
    _preset("log-weight", "record", "body", ("weight",), action="body.measurement.create"),
    _preset("log-body-composition", "record", "body", action="body.measurement.create"),
    _preset("correct-body-measurement", "correct", "body", action="body.measurement.correct"),
)

PRESETS_BY_ID = {item.template_id: item for item in LEGACY_PRESETS}


if len(PRESETS_BY_ID) != len(LEGACY_PRESETS):
    raise RuntimeError("AI legacy preset ids must be unique.")


__all__ = ["LEGACY_PRESETS", "PRESETS_BY_ID"]
