from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import current_app

from app.extensions import db
from app.models import (
    PlannedWorkout,
    TrainingPlanVersion,
    TrainingSession,
    WorkoutSessionDraft,
)


DRAFT_SCHEMA_VERSION = "1.0"
_FIELD_NAME = re.compile(r"^[A-Za-z0-9_:-]{1,120}$")
_FORBIDDEN_NAMES = {
    "authorization",
    "cookie",
    "csrf_token",
    "password",
    "secret",
    "token",
}
_CONTEXT_KEYS = {
    "form_url",
    "plan_public_id",
    "training_plan_version_public_id",
    "planned_workout_public_id",
    "planned_week_number",
    "planned_day_number",
}


class WorkoutDraftError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def _uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise WorkoutDraftError(
            "invalid_draft", f"{field} must be a UUID."
        ) from error


def _safe_field_value(value: Any) -> bool:
    if isinstance(value, (str, bool, int, float)) or value is None:
        if isinstance(value, str):
            return len(value) <= 10000
        if isinstance(value, float):
            return math.isfinite(value)
        return True
    if isinstance(value, list) and len(value) <= 100:
        return all(
            _safe_field_value(item) and not isinstance(item, list)
            for item in value
        )
    return False


def validate_draft_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WorkoutDraftError("invalid_draft", "Draft payload must be an object.")
    if set(payload) - {
        "schema_version",
        "client_submission_id",
        "context",
        "fields",
        "updated_at",
        "expires_at",
    }:
        raise WorkoutDraftError(
            "invalid_draft", "Draft payload contains unsupported fields."
        )
    if payload.get("schema_version") != DRAFT_SCHEMA_VERSION:
        raise WorkoutDraftError(
            "invalid_draft", "Unsupported workout draft schema version."
        )
    payload["client_submission_id"] = _uuid(
        payload.get("client_submission_id"), "client_submission_id"
    )
    context = payload.get("context")
    fields = payload.get("fields")
    if not isinstance(context, dict) or set(context) - _CONTEXT_KEYS:
        raise WorkoutDraftError("invalid_draft", "Draft context is invalid.")
    required_context = {
        "form_url",
        "plan_public_id",
        "training_plan_version_public_id",
        "planned_week_number",
        "planned_day_number",
    }
    if not required_context.issubset(context):
        raise WorkoutDraftError("invalid_draft", "Draft context is incomplete.")
    for key in ("plan_public_id", "training_plan_version_public_id"):
        context[key] = _uuid(context.get(key), key)
    if context.get("planned_workout_public_id"):
        context["planned_workout_public_id"] = _uuid(
            context["planned_workout_public_id"], "planned_workout_public_id"
        )
    form_url = context.get("form_url")
    if (
        not isinstance(form_url, str)
        or not form_url.startswith("/training-sessions/new")
        or len(form_url) > 500
        or "\\" in form_url
    ):
        raise WorkoutDraftError("invalid_draft", "Draft form URL is invalid.")
    for key, minimum, maximum in (
        ("planned_week_number", 1, 1000),
        ("planned_day_number", 1, 7),
    ):
        value = context.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            raise WorkoutDraftError("invalid_draft", f"{key} is invalid.")
    if not isinstance(fields, dict) or len(fields) > 1000:
        raise WorkoutDraftError("invalid_draft", "Draft fields are invalid.")
    for name, value in fields.items():
        normalized = str(name).casefold()
        if (
            not isinstance(name, str)
            or not _FIELD_NAME.fullmatch(name)
            or normalized in _FORBIDDEN_NAMES
            or "token" in normalized
            or not _safe_field_value(value)
        ):
            raise WorkoutDraftError(
                "invalid_draft", "Draft contains an unsafe form field."
            )
    size = len(canonical_payload_bytes(payload))
    if size > current_app.config["WORKOUT_DRAFT_MAX_BYTES"]:
        raise WorkoutDraftError(
            "draft_too_large", "The workout draft is too large.", 413
        )
    return payload


def _owned_context(
    user_id: int, context: dict[str, Any]
) -> tuple[TrainingPlanVersion, PlannedWorkout | None]:
    version = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.user_id == user_id,
            TrainingPlanVersion.public_id
            == context["training_plan_version_public_id"],
        )
    ).scalar_one_or_none()
    if (
        version is None
        or version.training_plan.public_id != context["plan_public_id"]
    ):
        raise WorkoutDraftError("not_found", "Workout context was not found.", 404)

    week = next(
        (
            item
            for item in version.content["data"]["weeks"]
            if item["week_number"] == context["planned_week_number"]
        ),
        None,
    )
    day = next(
        (
            item
            for item in (week or {}).get("days", [])
            if item["day_number"] == context["planned_day_number"]
        ),
        None,
    )
    if day is None or not day.get("exercises"):
        raise WorkoutDraftError("not_found", "Workout context was not found.", 404)

    planned = None
    planned_public_id = context.get("planned_workout_public_id")
    if planned_public_id:
        planned = db.session.execute(
            db.select(PlannedWorkout).where(
                PlannedWorkout.user_id == user_id,
                PlannedWorkout.public_id == planned_public_id,
                PlannedWorkout.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if (
            planned is None
            or planned.training_plan_version_id != version.id
            or planned.training_plan_id != version.training_plan_id
        ):
            raise WorkoutDraftError("not_found", "Workout context was not found.", 404)
    return version, planned


def create_draft(payload: Any, user_id: int) -> tuple[WorkoutSessionDraft, bool]:
    clean = validate_draft_payload(payload)
    version, planned = _owned_context(user_id, clean["context"])
    digest = payload_hash(clean)
    existing = db.session.execute(
        db.select(WorkoutSessionDraft).where(
            WorkoutSessionDraft.user_id == user_id,
            WorkoutSessionDraft.client_submission_id
            == clean["client_submission_id"],
        )
    ).scalar_one_or_none()
    if existing is not None:
        if is_expired(existing):
            db.session.delete(existing)
            db.session.flush()
            existing = None
    if existing is not None:
        if existing.payload_hash == digest:
            return existing, True
        raise WorkoutDraftError(
            "draft_conflict",
            "A newer or different draft already uses this submission ID.",
            409,
        )
    now = utcnow()
    draft = WorkoutSessionDraft(
        user_id=user_id,
        training_plan_id=version.training_plan_id,
        training_plan_version_id=version.id,
        planned_workout_id=planned.id if planned else None,
        planned_week_number=clean["context"]["planned_week_number"],
        planned_day_number=clean["context"]["planned_day_number"],
        client_submission_id=clean["client_submission_id"],
        payload_json=clean,
        payload_hash=digest,
        schema_version=DRAFT_SCHEMA_VERSION,
        expires_at=now
        + timedelta(days=current_app.config["WORKOUT_DRAFT_TTL_DAYS"]),
    )
    db.session.add(draft)
    db.session.commit()
    return draft, False


def update_draft(
    draft: WorkoutSessionDraft,
    payload: Any,
    user_id: int,
    expected_revision: int,
) -> tuple[WorkoutSessionDraft, bool]:
    if draft.user_id != user_id:
        raise WorkoutDraftError("not_found", "Workout draft was not found.", 404)
    db.session.refresh(draft, with_for_update=True)
    if draft.revision != expected_revision:
        raise WorkoutDraftError(
            "draft_conflict", "The workout draft changed on another client.", 409
        )
    clean = validate_draft_payload(payload)
    if clean["client_submission_id"] != draft.client_submission_id:
        raise WorkoutDraftError(
            "draft_conflict", "Submission ID cannot be changed.", 409
        )
    version, planned = _owned_context(user_id, clean["context"])
    digest = payload_hash(clean)
    if digest == draft.payload_hash:
        return draft, True
    draft.training_plan_id = version.training_plan_id
    draft.training_plan_version_id = version.id
    draft.planned_workout_id = planned.id if planned else None
    draft.planned_week_number = clean["context"]["planned_week_number"]
    draft.planned_day_number = clean["context"]["planned_day_number"]
    draft.payload_json = clean
    draft.payload_hash = digest
    draft.revision += 1
    draft.updated_at = utcnow()
    draft.expires_at = utcnow() + timedelta(
        days=current_app.config["WORKOUT_DRAFT_TTL_DAYS"]
    )
    db.session.commit()
    return draft, False


def owned_draft(public_id: str, user_id: int) -> WorkoutSessionDraft | None:
    return db.session.execute(
        db.select(WorkoutSessionDraft).where(
            WorkoutSessionDraft.public_id == public_id,
            WorkoutSessionDraft.user_id == user_id,
        )
    ).scalar_one_or_none()


def is_expired(draft: WorkoutSessionDraft) -> bool:
    return _aware(draft.expires_at) <= utcnow()


def latest_context_draft(
    *,
    user_id: int,
    version_id: int,
    week_number: int,
    day_number: int,
    planned_workout_id: int | None,
) -> WorkoutSessionDraft | None:
    statement = db.select(WorkoutSessionDraft).where(
        WorkoutSessionDraft.user_id == user_id,
        WorkoutSessionDraft.training_plan_version_id == version_id,
        WorkoutSessionDraft.planned_week_number == week_number,
        WorkoutSessionDraft.planned_day_number == day_number,
        WorkoutSessionDraft.expires_at > utcnow(),
    )
    if planned_workout_id is None:
        statement = statement.where(WorkoutSessionDraft.planned_workout_id.is_(None))
    else:
        statement = statement.where(
            WorkoutSessionDraft.planned_workout_id == planned_workout_id
        )
    return db.session.execute(
        statement.order_by(WorkoutSessionDraft.updated_at.desc()).limit(1)
    ).scalar_one_or_none()


def serialize_draft(draft: WorkoutSessionDraft, *, include_payload: bool) -> dict[str, Any]:
    document = {
        "public_id": draft.public_id,
        "client_submission_id": draft.client_submission_id,
        "schema_version": draft.schema_version,
        "revision": draft.revision,
        "updated_at": _aware(draft.updated_at).isoformat(),
        "expires_at": _aware(draft.expires_at).isoformat(),
    }
    if include_payload:
        document["payload"] = draft.payload_json
    return document


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def cleanup_report(*, apply: bool) -> dict[str, int | str]:
    now = utcnow()
    old_cutoff = now - timedelta(
        days=max(14, current_app.config["WORKOUT_DRAFT_TTL_DAYS"] * 2)
    )
    drafts = db.session.execute(db.select(WorkoutSessionDraft)).scalars().all()
    expired = []
    orphaned = []
    too_large = []
    inconsistent_hash = []
    completed = []
    old_active = []
    for draft in drafts:
        try:
            size = len(canonical_payload_bytes(draft.payload_json))
            digest = payload_hash(draft.payload_json)
        except (TypeError, ValueError):
            size = current_app.config["WORKOUT_DRAFT_MAX_BYTES"] + 1
            digest = ""
        if _aware(draft.expires_at) <= now:
            expired.append(draft)
        if draft.training_plan_version is None or draft.user is None:
            orphaned.append(draft)
        if size > current_app.config["WORKOUT_DRAFT_MAX_BYTES"]:
            too_large.append(draft)
        if digest != draft.payload_hash:
            inconsistent_hash.append(draft)
        if db.session.execute(
            db.select(TrainingSession.id).where(
                TrainingSession.user_id == draft.user_id,
                TrainingSession.client_submission_id == draft.client_submission_id,
            )
        ).scalar_one_or_none() is not None:
            completed.append(draft)
        if _aware(draft.updated_at) < old_cutoff and _aware(draft.expires_at) > now:
            old_active.append(draft)
    removable = {
        draft.id: draft
        for group in (expired, orphaned, too_large, inconsistent_hash, completed)
        for draft in group
    }
    if apply:
        for draft in removable.values():
            db.session.delete(draft)
        db.session.commit()
    return {
        "mode": "apply" if apply else "dry-run",
        "expired_drafts": len(expired),
        "orphaned_drafts": len(orphaned),
        "oversized_drafts": len(too_large),
        "hash_mismatches": len(inconsistent_hash),
        "completed_session_drafts": len(completed),
        "old_active_drafts_report_only": len(old_active),
        "records_updated": 0,
        "records_deleted": len(removable) if apply else 0,
    }
