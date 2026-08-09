"""Read-only, owner-scoped history and progress calculations for Android."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import uuid

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy import and_, or_
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Exercise, TrainingSession, TrainingSessionExercise
from app.services.exercise_identity import normalize_exercise_name
from app.services.mobile_sync import MobileSyncError, rfc3339


RANGE_DAYS = {"7": 7, "30": 30, "90": 90, "180": 180, "365": 365}
WEIGHT_VOLUME_MODES = {
    "direct_total",
    "per_side",
    "bar_plus_per_side",
    "machine_initial_total",
    "machine_initial_per_side",
    "machine_external_per_side_initial_total",
    "selector_stack",
    "dumbbell_each",
}
NON_COMPARABLE_MODES = {"bodyweight", "bodyweight_plus", "assistance", "duration_distance"}
TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class ExerciseDescriptor:
    public_id: str
    name: str
    normalized_names: frozenset[str]


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except Exception:
        return None
    return result if result.is_finite() else None


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP), "f")


def _load_mode(training_set) -> str:
    details = training_set.load_details_json or {}
    mode = details.get("load_mode")
    return mode if mode in WEIGHT_VOLUME_MODES | NON_COMPARABLE_MODES else "direct_total"


def _set_volume(training_set) -> Decimal | None:
    mode = _load_mode(training_set)
    weight = _decimal(training_set.weight_kg)
    if mode not in WEIGHT_VOLUME_MODES or weight is None or weight < 0 or training_set.reps < 1:
        return None
    return weight * training_set.reps


def _session_volume(record: TrainingSession) -> tuple[Decimal | None, bool]:
    sets = [item for exercise in record.exercises for item in exercise.sets]
    values = [_set_volume(item) for item in sets]
    available = [item for item in values if item is not None]
    return (sum(available, Decimal("0")) if available else None, len(available) != len(sets))


def _session_name(record: TrainingSession) -> str:
    if record.planned_workout is not None:
        return record.planned_workout.title_snapshot
    return record.training_plan.name


def _source(record: TrainingSession) -> str:
    if record.source_device_id is not None:
        return "device_sync"
    if record.source_file_id is not None:
        return "import"
    return "manual"


def _session_options():
    return (
        selectinload(TrainingSession.exercises).selectinload(TrainingSessionExercise.sets),
        selectinload(TrainingSession.planned_workout),
        selectinload(TrainingSession.training_plan),
        selectinload(TrainingSession.training_plan_version),
    )


def _identity_index(
    user_id: int,
) -> tuple[dict[str, ExerciseDescriptor], dict[str, ExerciseDescriptor]]:
    identities = db.session.execute(
        db.select(Exercise)
        .where(Exercise.user_id == user_id)
        .options(selectinload(Exercise.aliases))
    ).scalars().all()
    by_name: dict[str, ExerciseDescriptor] = {}
    by_public: dict[str, ExerciseDescriptor] = {}
    for identity in identities:
        names = frozenset(
            {identity.normalized_name, *(alias.normalized_name for alias in identity.aliases)}
        )
        descriptor = ExerciseDescriptor(identity.public_id, identity.canonical_name, names)
        by_public[descriptor.public_id] = descriptor
        for name in names:
            by_name[name] = descriptor
    occurrences = db.session.execute(
        db.select(
            TrainingSessionExercise.id,
            TrainingSessionExercise.public_id,
            TrainingSessionExercise.name,
        )
        .where(TrainingSessionExercise.user_id == user_id)
        .order_by(TrainingSessionExercise.id)
    ).all()
    for occurrence in occurrences:
        normalized = normalize_exercise_name(occurrence.name)
        if normalized in by_name:
            continue
        descriptor = ExerciseDescriptor(
            occurrence.public_id, occurrence.name, frozenset({normalized})
        )
        by_name[normalized] = descriptor
        by_public[descriptor.public_id] = descriptor
    return by_name, by_public


def _cursor_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="mobile-history-v1")


def _encode_history_cursor(record: TrainingSession) -> str:
    return _cursor_serializer().dumps([rfc3339(record.performed_at), record.public_id])


def _decode_history_cursor(value: str) -> tuple[datetime, str]:
    try:
        payload = _cursor_serializer().loads(value)
        moment = datetime.fromisoformat(payload[0].replace("Z", "+00:00"))
        public_id = str(uuid.UUID(payload[1]))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment, public_id
    except (BadData, ValueError, TypeError, IndexError) as error:
        raise MobileSyncError("invalid_cursor", "El cursor de historial no es válido.") from error


def _date_boundary(value: date, *, end: bool = False) -> datetime:
    if end:
        return datetime.combine(value + timedelta(days=1), time.min, timezone.utc)
    return datetime.combine(value, time.min, timezone.utc)


def history_page(
    *,
    user_id: int,
    limit: int,
    cursor: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    exercise_public_id: str | None = None,
) -> dict:
    if limit < 1 or limit > 100:
        raise MobileSyncError("invalid_limit", "limit debe estar entre 1 y 100.")
    if date_from and date_to and date_from > date_to:
        raise MobileSyncError("invalid_range", "date_from no puede ser posterior a date_to.")
    query = db.select(TrainingSession).where(
        TrainingSession.user_id == user_id,
        TrainingSession.deleted_at.is_(None),
    )
    if date_from:
        query = query.where(TrainingSession.performed_at >= _date_boundary(date_from))
    if date_to:
        query = query.where(TrainingSession.performed_at < _date_boundary(date_to, end=True))
    if exercise_public_id:
        try:
            exercise_public_id = str(uuid.UUID(exercise_public_id))
        except ValueError as error:
            raise MobileSyncError("invalid_id", "El ID de ejercicio no es válido.") from error
        by_name, by_public = _identity_index(user_id)
        identity = by_public.get(exercise_public_id)
        if identity is None:
            raise MobileSyncError("not_found", "Ejercicio no encontrado.", 404)
        names = identity.normalized_names
        matching = db.select(TrainingSessionExercise.training_session_id).where(
            TrainingSessionExercise.user_id == user_id,
            db.func.lower(TrainingSessionExercise.name).in_(names),
        )
        query = query.where(TrainingSession.id.in_(matching))
    if cursor:
        moment, public_id = _decode_history_cursor(cursor)
        query = query.where(
            or_(
                TrainingSession.performed_at < moment,
                and_(TrainingSession.performed_at == moment, TrainingSession.public_id < public_id),
            )
        )
    records = db.session.execute(
        query.options(*_session_options())
        .order_by(TrainingSession.performed_at.desc(), TrainingSession.public_id.desc())
        .limit(limit + 1)
    ).scalars().all()
    has_more = len(records) > limit
    page = records[:limit]
    return {
        "schema_version": "1.0",
        "items": [_history_item(item) for item in page],
        "next_cursor": _encode_history_cursor(page[-1]) if has_more and page else None,
        "has_more": has_more,
    }


def _history_item(record: TrainingSession) -> dict:
    volume, partial = _session_volume(record)
    return {
        "public_id": record.public_id,
        "performed_at": rfc3339(record.performed_at),
        "completed_at": rfc3339(record.completed_at or record.performed_at),
        "name": _session_name(record),
        "duration_seconds": record.duration_seconds,
        "exercise_count": len(record.exercises),
        "set_count": sum(len(item.sets) for item in record.exercises),
        "volume_kg": _text(volume),
        "volume_partial": partial,
        "source": _source(record),
        "sync_status": "synced",
    }


def history_detail(user_id: int, public_id: str) -> dict:
    try:
        public_id = str(uuid.UUID(public_id))
    except ValueError as error:
        raise MobileSyncError("not_found", "Sesión no encontrada.", 404) from error
    record = db.session.execute(
        db.select(TrainingSession)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSession.public_id == public_id,
            TrainingSession.deleted_at.is_(None),
        )
        .options(*_session_options())
    ).scalar_one_or_none()
    if record is None:
        raise MobileSyncError("not_found", "Sesión no encontrada.", 404)
    by_name, _ = _identity_index(user_id)
    item = _history_item(record)
    item.update(
        {
            "started_at": rfc3339(record.started_at or record.performed_at),
            "timezone": record.timezone or "UTC",
            "notes": record.notes,
            "planned_workout_id": record.planned_workout.public_id if record.planned_workout else None,
            "training_plan_id": record.training_plan.public_id,
            "training_plan_version_id": record.training_plan_version.public_id,
            "exercises": [
                _exercise_detail(exercise, by_name.get(normalize_exercise_name(exercise.name)))
                for exercise in record.exercises
            ],
        }
    )
    return {"schema_version": "1.0", **item}


def _component(details: dict, name: str) -> str | None:
    value = (details.get("components") or {}).get(name)
    return str(value.get("value")) if isinstance(value, dict) and value.get("value") is not None else None


def _exercise_detail(
    exercise: TrainingSessionExercise, identity: ExerciseDescriptor | None
) -> dict:
    return {
        "exercise_public_id": identity.public_id if identity else None,
        "exercise_order": exercise.exercise_order,
        "name": exercise.name,
        "notes": exercise.notes,
        "sets": [
            {
                "set_number": item.set_number,
                "weight_kg": _text(_decimal(item.weight_kg)),
                "load_mode": _load_mode(item),
                "display_load": (item.load_details_json or {}).get("display_total"),
                "reps": item.reps,
                "rir": _text(_decimal(item.rir)),
                "rpe": _text(_decimal(item.rpe)),
                "rest_seconds": item.rest_seconds,
                "duration_seconds": _component(item.load_details_json or {}, "duration_seconds"),
                "distance_meters": _component(item.load_details_json or {}, "distance_meters"),
                "notes": item.notes,
            }
            for item in exercise.sets
        ],
    }


def _period(value: str, now: datetime | None = None) -> tuple[datetime | None, datetime, datetime | None, datetime | None]:
    now = now or datetime.now(timezone.utc)
    if value == "all":
        return None, now, None, None
    days = RANGE_DAYS.get(value)
    if days is None:
        raise MobileSyncError("invalid_range", "range debe ser 7, 30, 90, 180, 365 o all.")
    start = now - timedelta(days=days)
    return start, now, start - timedelta(days=days), start


def _sessions_in_period(user_id: int, start: datetime | None, end: datetime) -> list[TrainingSession]:
    query = db.select(TrainingSession).where(
        TrainingSession.user_id == user_id,
        TrainingSession.deleted_at.is_(None),
        TrainingSession.performed_at < end,
    )
    if start is not None:
        query = query.where(TrainingSession.performed_at >= start)
    return db.session.execute(
        query.options(*_session_options()).order_by(TrainingSession.performed_at, TrainingSession.public_id)
    ).scalars().all()


def _summary_metrics(user_id: int, records: list[TrainingSession]) -> dict:
    by_name, _ = _identity_index(user_id)
    exercises = {
        by_name.get(normalize_exercise_name(item.name)).public_id
        if by_name.get(normalize_exercise_name(item.name)) is not None
        else normalize_exercise_name(item.name)
        for record in records
        for item in record.exercises
    }
    sets = [item for record in records for exercise in record.exercises for item in exercise.sets]
    volumes = [_set_volume(item) for item in sets]
    available = [item for item in volumes if item is not None]
    return {
        "sessions": len(records),
        "training_days": len({record.performed_at.date() for record in records}),
        "distinct_exercises": len(exercises),
        "completed_sets": len(sets),
        "total_reps": sum(item.reps for item in sets),
        "volume_kg": _text(sum(available, Decimal("0"))) if available else None,
        "volume_partial": len(available) != len(sets),
        "duration_seconds": sum(record.duration_seconds or 0 for record in records),
    }


def _comparison(current: dict, previous: dict | None) -> dict | None:
    if previous is None:
        return None
    result = {}
    for key in ("sessions", "training_days", "distinct_exercises", "completed_sets", "total_reps", "duration_seconds", "volume_kg"):
        current_value = _decimal(current[key]) or Decimal("0")
        previous_value = _decimal(previous[key]) or Decimal("0")
        result[key] = {
            "change": _text(current_value - previous_value),
            "percent": (
                _text(((current_value - previous_value) / previous_value) * Decimal("100"))
                if previous_value != 0
                else None
            ),
            "previous": _text(previous_value),
        }
    return result


def progress_summary(user_id: int, range_value: str) -> dict:
    start, end, previous_start, previous_end = _period(range_value)
    current = _summary_metrics(user_id, _sessions_in_period(user_id, start, end))
    previous = (
        _summary_metrics(user_id, _sessions_in_period(user_id, previous_start, previous_end))
        if previous_start is not None and previous_end is not None
        else None
    )
    return {
        "schema_version": "1.0",
        "range": range_value,
        "generated_at": rfc3339(end),
        "metrics": current,
        "comparison": _comparison(current, previous),
        "comparable_load_modes": sorted(WEIGHT_VOLUME_MODES),
    }


def _group_exercises(user_id: int, records: list[TrainingSession]):
    by_name, by_public = _identity_index(user_id)
    groups: dict[str, list[TrainingSessionExercise]] = defaultdict(list)
    for record in records:
        for exercise in record.exercises:
            identity = by_name.get(normalize_exercise_name(exercise.name))
            if identity is not None:
                groups[identity.public_id].append(exercise)
    return groups, by_public


def _exercise_payload(
    identity: ExerciseDescriptor, appearances: list[TrainingSessionExercise]
) -> dict:
    appearances = sorted(appearances, key=lambda item: (item.training_session.performed_at, item.id))
    sets = [item for appearance in appearances for item in appearance.sets]
    modes = {_load_mode(item) for item in sets}
    compatible_sets = [item for item in sets if _set_volume(item) is not None]
    load_comparable = len(modes) == 1 and bool(modes) and next(iter(modes)) in WEIGHT_VOLUME_MODES
    volumes = [_set_volume(item) for item in sets]
    total_volume = sum((item for item in volumes if item is not None), Decimal("0"))
    best_load = max((_decimal(item.weight_kg) for item in compatible_sets), default=None)
    best_reps = max(compatible_sets, key=lambda item: (item.reps, item.weight_kg), default=None)
    points = [_point(item) for item in appearances]
    trend = "insufficient_data"
    if load_comparable and len(points) >= 2:
        previous, current = points[-2], points[-1]
        current_load = Decimal(current["best_load_kg"] or "0")
        previous_load = Decimal(previous["best_load_kg"] or "0")
        trend = "up" if current_load > previous_load else "stable"
        if current_load < previous_load:
            trend = "down"
    return {
        "public_id": identity.public_id,
        "name": identity.name,
        "last_performed_at": rfc3339(appearances[-1].training_session.performed_at),
        "session_count": len({item.training_session_id for item in appearances}),
        "set_count": len(sets),
        "best_load_kg": _text(best_load) if load_comparable else None,
        "best_repetition_set": (
            {"reps": best_reps.reps, "weight_kg": _text(_decimal(best_reps.weight_kg))}
            if load_comparable and best_reps else None
        ),
        "volume_kg": _text(total_volume) if compatible_sets else None,
        "volume_partial": len(compatible_sets) != len(sets),
        "load_comparable": load_comparable,
        "load_modes": sorted(modes),
        "trend": trend,
    }


def progress_exercises(user_id: int, range_value: str) -> dict:
    start, end, _, _ = _period(range_value)
    records = _sessions_in_period(user_id, start, end)
    groups, identities = _group_exercises(user_id, records)
    items = [_exercise_payload(identities[key], value) for key, value in groups.items()]
    items.sort(key=lambda item: (item["last_performed_at"], item["public_id"]), reverse=True)
    return {"schema_version": "1.0", "range": range_value, "items": items}


def _point(appearance: TrainingSessionExercise) -> dict:
    sets = list(appearance.sets)
    compatible = [item for item in sets if _set_volume(item) is not None]
    volumes = [_set_volume(item) for item in compatible]
    rir = [_decimal(item.rir) for item in sets if _decimal(item.rir) is not None]
    rpe = [_decimal(item.rpe) for item in sets if _decimal(item.rpe) is not None]
    modes = {_load_mode(item) for item in sets}
    comparable = len(modes) == 1 and bool(modes) and next(iter(modes)) in WEIGHT_VOLUME_MODES
    return {
        "date": appearance.training_session.performed_at.date().isoformat(),
        "performed_at": rfc3339(appearance.training_session.performed_at),
        "session_public_id": appearance.training_session.public_id,
        "best_load_kg": _text(max((_decimal(item.weight_kg) for item in compatible), default=None)) if comparable else None,
        "best_reps": max((item.reps for item in compatible), default=None) if comparable else None,
        "volume_kg": _text(sum((item for item in volumes if item is not None), Decimal("0"))) if compatible else None,
        "set_count": len(sets),
        "average_rir": _text(sum(rir, Decimal("0")) / len(rir)) if rir else None,
        "average_rpe": _text(sum(rpe, Decimal("0")) / len(rpe)) if rpe else None,
        "load_comparable": comparable,
    }


def _personal_records(appearances: list[TrainingSessionExercise]) -> list[dict]:
    candidates = []
    session_volumes = []
    for appearance in appearances:
        compatible = [item for item in appearance.sets if _set_volume(item) is not None]
        modes = {_load_mode(item) for item in appearance.sets}
        if len(modes) != 1 or not modes or next(iter(modes)) not in WEIGHT_VOLUME_MODES:
            continue
        for item in compatible:
            volume = _set_volume(item)
            base = {
                "date": appearance.training_session.performed_at.date().isoformat(),
                "session_public_id": appearance.training_session.public_id,
                "set_index": item.set_number,
                "weight_kg": _decimal(item.weight_kg),
                "reps": item.reps,
                "volume_kg": volume,
            }
            candidates.append(base)
        session_volumes.append((sum((_set_volume(item) for item in compatible), Decimal("0")), appearance))
    if not candidates:
        return []
    definitions = [
        ("highest_load", max(candidates, key=lambda item: (item["weight_kg"], item["reps"], item["date"])), "weight_kg", "kg"),
        ("most_reps_at_comparable_load", max(candidates, key=lambda item: (item["reps"], item["weight_kg"], item["date"])), "reps", "reps"),
        ("highest_set_volume", max(candidates, key=lambda item: (item["volume_kg"], item["weight_kg"], item["date"])), "volume_kg", "kg"),
    ]
    result = [
        {
            "type": kind,
            "value": str(row[field]) if field == "reps" else _text(row[field]),
            "unit": unit,
            "date": row["date"],
            "session_public_id": row["session_public_id"],
            "set_index": row["set_index"],
        }
        for kind, row, field, unit in definitions
    ]
    if session_volumes:
        value, appearance = max(session_volumes, key=lambda item: (item[0], item[1].training_session.performed_at))
        result.append(
            {
                "type": "highest_session_volume",
                "value": _text(value),
                "unit": "kg",
                "date": appearance.training_session.performed_at.date().isoformat(),
                "session_public_id": appearance.training_session.public_id,
                "set_index": None,
            }
        )
    return result


def progress_exercise_detail(user_id: int, public_id: str, range_value: str) -> dict:
    try:
        public_id = str(uuid.UUID(public_id))
    except ValueError as error:
        raise MobileSyncError("not_found", "Ejercicio no encontrado.", 404) from error
    start, end, _, _ = _period(range_value)
    records = _sessions_in_period(user_id, start, end)
    groups, identities = _group_exercises(user_id, records)
    identity = identities.get(public_id)
    if identity is None:
        raise MobileSyncError("not_found", "Ejercicio no encontrado.", 404)
    appearances = groups.get(public_id, [])
    summary = _exercise_payload(identity, appearances) if appearances else {
        "public_id": identity.public_id,
        "name": identity.name,
        "last_performed_at": None,
        "session_count": 0,
        "set_count": 0,
        "best_load_kg": None,
        "best_repetition_set": None,
        "volume_kg": None,
        "volume_partial": False,
        "load_comparable": False,
        "load_modes": [],
        "trend": "insufficient_data",
    }
    return {
        "schema_version": "1.0",
        "range": range_value,
        "exercise": summary,
        "points": [_point(item) for item in appearances],
        "personal_records": _personal_records(appearances),
        "recent_sessions": [_history_item(item.training_session) for item in reversed(appearances[-10:])],
    }
