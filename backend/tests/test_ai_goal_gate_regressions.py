from __future__ import annotations

import pytest

from app.extensions import db
from app.models import User
from app.services.ai.capabilities.domains.goal_actions import GOAL_UPDATE
from app.services.ai.capabilities.types import CapabilityError


@pytest.mark.parametrize("unit_alias", ("count", "counts", "conteo"))
@pytest.mark.parametrize(
    ("goal_type", "canonical_type", "canonical_unit"),
    (
        ("steps", "daily_steps", "step"),
        ("pasos", "daily_steps", "step"),
        ("step goal", "daily_steps", "step"),
        ("training_sessions_per_week", "training_sessions_per_week", "session"),
        ("active_days_per_week", "active_days_per_week", "day"),
        ("weight logging", "weight_logging_frequency", "log"),
    ),
)
def test_goal_count_aliases_preserve_compatible_count_units(
    app, user, unit_alias, goal_type, canonical_type, canonical_unit
):
    with app.app_context():
        account = db.session.get(User, user)
        normalized = GOAL_UPDATE.validate(
            account,
            {"goal_type": goal_type, "target_value": "10", "unit": unit_alias},
            allow_incomplete=False,
        )
        assert normalized["goal_type"] == canonical_type
        assert normalized["unit"] == canonical_unit


@pytest.mark.parametrize("unit_alias", ("count", "counts", "conteo"))
@pytest.mark.parametrize(
    "goal_type",
    (
        "protein",
        "nutrition_protein",
        "calories",
        "nutrition_calories",
        "carbohydrates",
        "nutrition_carbohydrates",
        "fat",
        "nutrition_fat",
    ),
)
def test_goal_count_aliases_cannot_become_mass_or_energy(app, user, unit_alias, goal_type):
    with app.app_context():
        account = db.session.get(User, user)
        with pytest.raises(CapabilityError) as rejected:
            GOAL_UPDATE.validate(
                account,
                {"goal_type": goal_type, "target_value": "150", "unit": unit_alias},
                allow_incomplete=False,
            )
        assert rejected.value.code == "invalid_goal_contract"


@pytest.mark.parametrize(
    ("goal_type", "unit_alias", "canonical_type", "canonical_unit"),
    (
        ("protein", "grams", "nutrition_protein", "g"),
        ("proteína", "gramos", "nutrition_protein", "g"),
        ("calories", "calorías", "nutrition_calories", "kcal"),
        ("carbohydrates", "gram", "nutrition_carbohydrates", "g"),
        ("fat", "gramo", "nutrition_fat", "g"),
    ),
)
def test_goal_mass_and_energy_aliases_remain_valid(
    app, user, goal_type, unit_alias, canonical_type, canonical_unit
):
    with app.app_context():
        account = db.session.get(User, user)
        normalized = GOAL_UPDATE.validate(
            account,
            {"goal_type": goal_type, "target_value": "150", "unit": unit_alias},
            allow_incomplete=False,
        )
        assert normalized["goal_type"] == canonical_type
        assert normalized["unit"] == canonical_unit


@pytest.mark.parametrize(
    ("goal_type", "unit"),
    (("steps", "grams"), ("protein", "steps"), ("calories", "grams")),
)
def test_goal_incompatible_specific_unit_aliases_still_fail(app, user, goal_type, unit):
    with app.app_context():
        account = db.session.get(User, user)
        with pytest.raises(CapabilityError) as rejected:
            GOAL_UPDATE.validate(
                account,
                {"goal_type": goal_type, "target_value": "150", "unit": unit},
                allow_incomplete=False,
            )
        assert rejected.value.code == "invalid_goal_contract"
