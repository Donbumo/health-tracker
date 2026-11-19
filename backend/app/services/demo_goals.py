"""Explicit, additive goals for the historical fictitious DEMO account only."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from uuid import NAMESPACE_URL, uuid5

from flask import current_app

from app.extensions import db
from app.models import User, UserGoal
from app.services.engagement import create_goal


DEMO_EMAIL = "demo@healthtracker.test"
DEMO_PUBLIC_ID = str(uuid5(NAMESPACE_URL, "health-tracker/demo-history/v1/account"))
SOURCE = "demo_goals_v1"
START = date(2026, 10, 1)
SPECS = (
    ("nutrition_calories", 2350, "kcal", "daily"),
    ("nutrition_protein", 155, "g", "daily"),
    ("nutrition_carbohydrates", 265, "g", "daily"),
    ("nutrition_fat", 75, "g", "daily"),
    ("daily_steps", 8000, "step", "daily"),
    ("training_sessions_per_week", 3, "session", "weekly"),
    ("weight_logging_frequency", 7, "log", "weekly"),
)


def goal_id(goal_type: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"health-tracker/demo-goals/v1/{goal_type}"))


def seed_demo_goals(*, confirmed=False, confirm_production=False) -> dict:
    """Validate opt-in, lock DEMO, call the official service. Caller commits.

    Conflicts are reported per type and preserved; failures roll back at the CLI.
    No account/password/history is created or modified here.
    """
    enabled = current_app.config.get("DEMO_GOALS_ENABLED", os.getenv("DEMO_GOALS_ENABLED", ""))
    environment = current_app.config.get("DEMO_GOALS_ENVIRONMENT", os.getenv("DEMO_GOALS_ENVIRONMENT", ""))
    if str(enabled).lower() not in {"true", "1"} or not confirmed:
        raise ValueError("Se requiere DEMO_GOALS_ENABLED y confirmación explícita.")
    if environment not in {"test", "development", "production"}:
        raise ValueError("DEMO_GOALS_ENVIRONMENT debe ser test, development o production.")
    if environment == "production" and not confirm_production:
        raise ValueError("Producción requiere --confirm-production además de --confirm.")
    if confirm_production and environment != "production":
        raise ValueError("--confirm-production requiere DEMO_GOALS_ENVIRONMENT=production.")
    if environment == "test" and not current_app.testing:
        raise ValueError("El entorno test requiere TESTING.")
    labels = [current_app.config.get(k, os.getenv(k, "")) for k in ("APP_ENV", "FLASK_ENV", "ENV")]
    if any(str(label).lower() in {"production", "prod"} for label in labels) and environment != "production":
        raise ValueError("El entorno productivo requiere la confirmación de producción.")
    owner = db.session.execute(db.select(User).where(
        User.public_id == DEMO_PUBLIC_ID,
    ).with_for_update()).scalar_one_or_none()
    if (owner is None or owner.username != DEMO_EMAIL or owner.email != DEMO_EMAIL
            or owner.display_name != "Health Tracker Demo" or owner.role != "user"):
        raise ValueError("No se verificó la identidad de la cuenta histórica DEMO.")
    rows = db.session.execute(db.select(UserGoal).where(
        UserGoal.user_id == owner.id,
    ).with_for_update()).scalars().all()
    # Only inspect public identifiers outside DEMO to reject collisions, never payloads.
    occupied = set(db.session.execute(db.select(UserGoal.public_id).where(
        UserGoal.public_id.in_([goal_id(spec[0]) for spec in SPECS]),
        UserGoal.user_id != owner.id,
    )).scalars())
    result = {"created": [], "reused": [], "conflicts": []}
    goal_timezone = owner.timezone or "UTC"
    for kind, target, unit, period in SPECS:
        public_id = goal_id(kind)
        same_id = next((row for row in rows if row.public_id == public_id), None)
        conflicting = any(row.public_id != public_id and row.goal_type == kind
                          and row.state != "archived" and (row.end_date is None or row.end_date >= START)
                          for row in rows)
        exact = same_id is not None and all((
            same_id.goal_type == kind, same_id.target_value == Decimal(target),
            same_id.unit == unit, same_id.period == period, same_id.start_date == START,
            same_id.end_date is None, same_id.state == "active", same_id.source == SOURCE,
            same_id.revision == 1, same_id.related_public_id is None,
            same_id.timezone == goal_timezone, same_id.applicable_days_json == list(range(1, 8)),
        ))
        if public_id in occupied or conflicting or (same_id is not None and not exact):
            result["conflicts"].append(kind)
        elif exact:
            result["reused"].append(kind)
        else:
            row = create_goal(owner.id, {
                "public_id": public_id, "goal_type": kind, "target_value": target,
                "unit": unit, "period": period, "timezone": goal_timezone,
                "start_date": START.isoformat(),
            })
            row.source = SOURCE
            result["created"].append(kind)
    db.session.flush()
    return result
