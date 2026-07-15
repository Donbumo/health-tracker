import hashlib
import json
from datetime import datetime, timezone

from app.extensions import db
from app.models import TrainingPlan, TrainingPlanVersion


CAPABILITIES = {
    "offline_sync_push": True,
    "incremental_pull": True,
    "planned_workouts": True,
    "completed_workouts": True,
    "watch_bridge": False,
    "fit_output": False,
    "backup_zip": True,
    "raw_file_import": True,
    "advanced_exports": True,
    "companion_delivery": True,
    "capability_negotiation": True,
    "progress_checkpoints": True,
    "workout_package": True,
    "bluetooth_bridge": False,
    "continuous_telemetry": False,
    "vendor_huawei": False,
    "vendor_garmin": False,
    "vendor_magene": False,
}


def rfc3339(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def active_routine(user_id: int) -> dict | None:
    # There is one active version per plan but no account-wide active-plan flag.
    # API v1 deterministically exposes the most recently updated owned plan.
    plan = db.session.execute(
        db.select(TrainingPlan)
        .where(TrainingPlan.user_id == user_id)
        .order_by(TrainingPlan.updated_at.desc(), TrainingPlan.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if plan is None:
        return None
    version = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.training_plan_id == plan.id,
            TrainingPlanVersion.user_id == user_id,
            TrainingPlanVersion.version_number == plan.active_version_number,
        )
    ).scalar_one_or_none()
    if version is None:
        return None
    snapshot = {
        "schema_version": "1.0",
        "plan_id": plan.public_id,
        "version_id": version.public_id,
        "version": version.version_number,
        "name": plan.name,
        "description": plan.description,
        "days": [
            {**day, "week_number": week["week_number"]}
            for week in version.content["data"]["weeks"]
            for day in week["days"]
        ],
        "version_created_at": rfc3339(version.created_at),
        "plan_updated_at": rfc3339(plan.updated_at),
        "selection_policy": "most_recent_plan_active_version",
    }
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    snapshot["etag"] = hashlib.sha256(encoded).hexdigest()
    return snapshot
