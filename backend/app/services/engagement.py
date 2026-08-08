from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (
    DailyEnergy,
    DailyNutrition,
    PlannedWorkout,
    ReminderEvent,
    ReminderRule,
    TrainingPlan,
    TrainingSession,
    User,
    UserGoal,
    WeighIn,
)
from app.models.engagement import GOAL_TYPES, REMINDER_TYPES
from app.services.mobile_sync import MobileSyncError, rfc3339, validate_timezone


GOAL_STATES = {"active", "paused", "completed", "archived"}
GOAL_PERIODS = {"daily", "weekly", "selected_days", "active_plan", "scheduled_workouts"}
GOAL_CONTRACT = {
    "training_sessions_per_week": ({"session"}, {"weekly"}),
    "active_days_per_week": ({"day"}, {"weekly"}),
    "daily_steps": ({"step"}, {"daily", "selected_days"}),
    "nutrition_calories": ({"kcal"}, {"daily", "selected_days"}),
    "nutrition_protein": ({"g"}, {"daily", "selected_days"}),
    "nutrition_carbohydrates": ({"g"}, {"daily", "selected_days"}),
    "nutrition_fat": ({"g"}, {"daily", "selected_days"}),
    "weight_logging_frequency": ({"log"}, {"daily", "weekly", "selected_days"}),
    "active_plan_tracking": ({"session"}, {"active_plan"}),
    "scheduled_workouts_completion": ({"workout"}, {"scheduled_workouts"}),
}
SNOOZE_OPTIONS = {15, 30, 60, "tomorrow"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value, field="public_id") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise MobileSyncError("invalid_id", f"{field} debe ser un UUID válido.") from error


def _date(value, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise MobileSyncError("invalid_date", f"{field} debe usar YYYY-MM-DD.") from error


def _time(value, field: str) -> time:
    try:
        parsed = time.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise MobileSyncError("invalid_time", f"{field} debe usar HH:MM.") from error
    if parsed.tzinfo is not None:
        raise MobileSyncError("invalid_time", f"{field} debe ser una hora local sin offset.")
    return parsed.replace(second=0, microsecond=0)


def _decimal(value, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise MobileSyncError("invalid_value", f"{field} debe ser numérico.") from error
    if not parsed.is_finite() or parsed <= 0 or parsed > Decimal("1000000"):
        raise MobileSyncError("invalid_value", f"{field} está fuera de rango.")
    return parsed.quantize(Decimal("0.001"))


def _days(value, *, required=False) -> list[int]:
    if value is None:
        return list(range(1, 8)) if required else []
    if not isinstance(value, list) or len(value) > 7 or any(
        isinstance(item, bool) or not isinstance(item, int) or item not in range(1, 8)
        for item in value
    ):
        raise MobileSyncError("invalid_days", "Los días deben ser valores ISO únicos entre 1 y 7.")
    if len(set(value)) != len(value):
        raise MobileSyncError("invalid_days", "Los días no pueden repetirse.")
    if required and not value:
        raise MobileSyncError("invalid_days", "Selecciona al menos un día.")
    return sorted(value)


def _number(value: Decimal | None):
    if value is None:
        return None
    return format(value, "f").rstrip("0").rstrip(".")


def _goal_values(payload: dict, *, creating: bool) -> dict:
    fields = {
        "public_id", "goal_type", "target_value", "unit", "period",
        "applicable_days", "timezone", "start_date", "end_date", "state",
        "related_public_id", "base_revision",
    }
    if set(payload) - fields:
        raise MobileSyncError("invalid_request", "El objetivo contiene campos no reconocidos.")
    if creating:
        required = {"goal_type", "target_value", "unit", "period", "timezone", "start_date"}
        if not required <= set(payload):
            raise MobileSyncError("invalid_request", "Faltan campos requeridos del objetivo.")
    values = {}
    if "goal_type" in payload:
        goal_type = payload["goal_type"]
        if goal_type not in GOAL_TYPES:
            raise MobileSyncError("invalid_goal_type", "El tipo de objetivo no está soportado.")
        values["goal_type"] = goal_type
    goal_type = values.get("goal_type")
    if "target_value" in payload:
        values["target_value"] = _decimal(payload["target_value"], "target_value")
    if "unit" in payload:
        unit = str(payload["unit"])
        if len(unit) > 32:
            raise MobileSyncError("invalid_unit", "La unidad no es válida.")
        values["unit"] = unit
    if "period" in payload:
        period = payload["period"]
        if period not in GOAL_PERIODS:
            raise MobileSyncError("invalid_period", "El periodo no está soportado.")
        values["period"] = period
    if goal_type and "unit" in values and "period" in values:
        units, periods = GOAL_CONTRACT[goal_type]
        if values["unit"] not in units or values["period"] not in periods:
            raise MobileSyncError("invalid_goal_contract", "La unidad o periodo no corresponde al tipo de objetivo.")
    if "applicable_days" in payload:
        values["applicable_days_json"] = _days(payload["applicable_days"], required=payload.get("period") == "selected_days")
    elif creating:
        values["applicable_days_json"] = list(range(1, 8))
    if "timezone" in payload:
        values["timezone"] = validate_timezone(payload["timezone"])
    if "start_date" in payload:
        values["start_date"] = _date(payload["start_date"], "start_date")
    if "end_date" in payload:
        values["end_date"] = None if payload["end_date"] in (None, "") else _date(payload["end_date"], "end_date")
    start = values.get("start_date")
    end = values.get("end_date")
    if start and end and end < start:
        raise MobileSyncError("invalid_date_range", "end_date no puede ser anterior a start_date.")
    if "state" in payload:
        if payload["state"] not in GOAL_STATES:
            raise MobileSyncError("invalid_state", "El estado del objetivo no es válido.")
        values["state"] = payload["state"]
    elif creating:
        values["state"] = "active"
    if "related_public_id" in payload:
        values["related_public_id"] = None if payload["related_public_id"] in (None, "") else _uuid(payload["related_public_id"], "related_public_id")
    if values.get("goal_type") == "active_plan_tracking" and not values.get("related_public_id"):
        raise MobileSyncError("related_resource_required", "Selecciona una rutina activa.")
    return values


def serialize_goal(record: UserGoal) -> dict:
    return {
        "public_id": record.public_id,
        "goal_type": record.goal_type,
        "target_value": _number(record.target_value),
        "unit": record.unit,
        "period": record.period,
        "applicable_days": record.applicable_days_json or [],
        "timezone": record.timezone,
        "start_date": record.start_date.isoformat(),
        "end_date": record.end_date.isoformat() if record.end_date else None,
        "state": record.state,
        "revision": record.revision,
        "source": record.source,
        "related_public_id": record.related_public_id,
        "created_at": rfc3339(record.created_at),
        "updated_at": rfc3339(record.updated_at),
    }


def list_goals(user_id: int, *, include_archived=False) -> list[dict]:
    statement = db.select(UserGoal).where(UserGoal.user_id == user_id)
    if not include_archived:
        statement = statement.where(UserGoal.state != "archived")
    rows = db.session.execute(statement.order_by(UserGoal.start_date, UserGoal.public_id)).scalars().all()
    return [serialize_goal(row) for row in rows]


def owned_goal(user_id: int, public_id: str, *, lock=False) -> UserGoal:
    statement = db.select(UserGoal).where(
        UserGoal.user_id == user_id, UserGoal.public_id == _uuid(public_id)
    )
    if lock:
        statement = statement.with_for_update()
    row = db.session.execute(statement).scalar_one_or_none()
    if row is None:
        raise MobileSyncError("not_found", "Objetivo no encontrado.", 404)
    return row


def create_goal(user_id: int, payload: dict) -> UserGoal:
    values = _goal_values(payload, creating=True)
    public_id = _uuid(payload.get("public_id") or uuid.uuid4())
    if db.session.execute(db.select(UserGoal.id).where(UserGoal.public_id == public_id)).scalar_one_or_none():
        raise MobileSyncError("conflict", "El identificador ya existe.", 409)
    if values.get("related_public_id"):
        plan = db.session.execute(db.select(TrainingPlan.id).where(
            TrainingPlan.user_id == user_id, TrainingPlan.public_id == values["related_public_id"]
        )).scalar_one_or_none()
        if plan is None:
            raise MobileSyncError("not_found", "Rutina no encontrada.", 404)
    row = UserGoal(public_id=public_id, user_id=user_id, source="manual", **values)
    db.session.add(row)
    db.session.flush()
    return row


def _revision(current: int, value) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MobileSyncError("base_revision_required", "Se requiere base_revision.")
    if value != current:
        raise MobileSyncError(
            "revision_conflict", "El recurso cambió en el servidor.", 409,
            {"server_revision": current, "conflict_code": "stale_revision"},
        )


def patch_goal(user_id: int, public_id: str, payload: dict) -> UserGoal:
    row = owned_goal(user_id, public_id, lock=True)
    _revision(row.revision, payload.get("base_revision"))
    values = _goal_values(payload, creating=False)
    merged_type = values.get("goal_type", row.goal_type)
    merged_unit = values.get("unit", row.unit)
    merged_period = values.get("period", row.period)
    units, periods = GOAL_CONTRACT[merged_type]
    if merged_unit not in units or merged_period not in periods:
        raise MobileSyncError("invalid_goal_contract", "La unidad o periodo no corresponde al tipo de objetivo.")
    merged_start = values.get("start_date", row.start_date)
    merged_end = values.get("end_date", row.end_date)
    if merged_end and merged_end < merged_start:
        raise MobileSyncError("invalid_date_range", "end_date no puede ser anterior a start_date.")
    for key, value in values.items():
        setattr(row, key, value)
    row.revision += 1
    row.updated_at = utcnow()
    db.session.flush()
    return row


def archive_goal(user_id: int, public_id: str, payload: dict) -> UserGoal:
    row = owned_goal(user_id, public_id, lock=True)
    if set(payload) != {"base_revision"}:
        raise MobileSyncError("invalid_request", "Se requiere únicamente base_revision.")
    _revision(row.revision, payload["base_revision"])
    row.state = "archived"
    row.revision += 1
    row.updated_at = utcnow()
    for rule in db.session.execute(db.select(ReminderRule).where(
        ReminderRule.user_id == user_id, ReminderRule.goal_id == row.id
    )).scalars():
        rule.enabled = False
        rule.next_occurrence = None
        rule.revision += 1
    db.session.flush()
    return row


def resolve_local_datetime(day: date, local_time: time, timezone_name: str) -> datetime:
    """Resolve a local wall time, choosing first overlap and moving DST gaps forward."""
    try:
        zone = ZoneInfo(timezone_name)
    except (TypeError, ZoneInfoNotFoundError) as error:
        raise MobileSyncError("invalid_timezone", "La zona horaria IANA no es válida.") from error
    naive = datetime.combine(day, local_time)
    candidate = naive.replace(tzinfo=zone, fold=0)
    roundtrip = candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
    if roundtrip != naive:
        if roundtrip < naive:
            # A backward overlap uses fold=0; the local logical key prevents a second event.
            return candidate.astimezone(timezone.utc)
        candidate = roundtrip.replace(tzinfo=zone, fold=0)
    return candidate.astimezone(timezone.utc)


def next_occurrence(local_time: time, days: list[int], timezone_name: str, lead_minutes: int, *, now=None) -> datetime:
    now = now or utcnow()
    zone = ZoneInfo(validate_timezone(timezone_name))
    local_today = now.astimezone(zone).date()
    allowed = set(days or range(1, 8))
    for offset in range(0, 15):
        candidate_day = local_today + timedelta(days=offset)
        if candidate_day.isoweekday() not in allowed:
            continue
        candidate = resolve_local_datetime(candidate_day, local_time, timezone_name) - timedelta(minutes=lead_minutes)
        if candidate > now:
            return candidate
    raise MobileSyncError("schedule_unavailable", "No se pudo calcular la próxima ocurrencia.", 409)


def _rule_values(payload: dict, user_id: int, *, creating: bool) -> dict:
    fields = {
        "public_id", "reminder_type", "goal_public_id", "local_time", "applicable_days",
        "lead_minutes", "quiet_start", "quiet_end", "quiet_timezone", "snooze_options",
        "max_per_day", "cooldown_minutes", "enabled", "timezone", "related_public_id",
        "base_revision",
    }
    if set(payload) - fields:
        raise MobileSyncError("invalid_request", "La regla contiene campos no reconocidos.")
    if creating and not {"reminder_type", "local_time", "timezone"} <= set(payload):
        raise MobileSyncError("invalid_request", "Faltan campos requeridos de la regla.")
    values = {}
    if "reminder_type" in payload:
        if payload["reminder_type"] not in REMINDER_TYPES:
            raise MobileSyncError("invalid_reminder_type", "El tipo de recordatorio no está soportado.")
        values["reminder_type"] = payload["reminder_type"]
    if "goal_public_id" in payload:
        goal = None if payload["goal_public_id"] in (None, "") else owned_goal(user_id, payload["goal_public_id"])
        values["goal_id"] = goal.id if goal else None
    if "local_time" in payload:
        values["local_time"] = _time(payload["local_time"], "local_time")
    if "applicable_days" in payload:
        values["applicable_days_json"] = _days(payload["applicable_days"], required=True)
    elif creating:
        values["applicable_days_json"] = list(range(1, 8))
    for field, minimum, maximum, default in (
        ("lead_minutes", 0, 10080, 0), ("max_per_day", 1, 10, 1),
        ("cooldown_minutes", 0, 1440, 60),
    ):
        if field in payload:
            value = payload[field]
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise MobileSyncError("invalid_limit", f"{field} está fuera de rango.")
            values[field] = value
        elif creating:
            values[field] = default
    quiet_present = "quiet_start" in payload or "quiet_end" in payload
    if quiet_present:
        if payload.get("quiet_start") in (None, "") and payload.get("quiet_end") in (None, ""):
            values.update(quiet_start=None, quiet_end=None, quiet_timezone=None)
        elif payload.get("quiet_start") in (None, "") or payload.get("quiet_end") in (None, ""):
            raise MobileSyncError("invalid_quiet_hours", "quiet_start y quiet_end deben configurarse juntos.")
        else:
            values["quiet_start"] = _time(payload["quiet_start"], "quiet_start")
            values["quiet_end"] = _time(payload["quiet_end"], "quiet_end")
            values["quiet_timezone"] = validate_timezone(payload.get("quiet_timezone") or payload.get("timezone"))
    if "snooze_options" in payload:
        options = payload["snooze_options"]
        if not isinstance(options, list) or not options or len(options) > 4 or any(item not in SNOOZE_OPTIONS for item in options):
            raise MobileSyncError("invalid_snooze", "Las opciones de posposición no son válidas.")
        values["snooze_options_json"] = list(dict.fromkeys(options))
    elif creating:
        values["snooze_options_json"] = [15, 30, 60, "tomorrow"]
    if "enabled" in payload:
        if type(payload["enabled"]) is not bool:
            raise MobileSyncError("invalid_enabled", "enabled debe ser booleano.")
        values["enabled"] = payload["enabled"]
    elif creating:
        values["enabled"] = True
    if "timezone" in payload:
        values["timezone"] = validate_timezone(payload["timezone"])
    if "related_public_id" in payload:
        values["related_public_id"] = None if payload["related_public_id"] in (None, "") else _uuid(payload["related_public_id"], "related_public_id")
    return values


def serialize_rule(record: ReminderRule) -> dict:
    return {
        "public_id": record.public_id,
        "reminder_type": record.reminder_type,
        "goal_public_id": record.goal.public_id if record.goal else None,
        "local_time": record.local_time.strftime("%H:%M"),
        "applicable_days": record.applicable_days_json or [],
        "lead_minutes": record.lead_minutes,
        "quiet_start": record.quiet_start.strftime("%H:%M") if record.quiet_start else None,
        "quiet_end": record.quiet_end.strftime("%H:%M") if record.quiet_end else None,
        "quiet_timezone": record.quiet_timezone,
        "snooze_options": record.snooze_options_json or [],
        "max_per_day": record.max_per_day,
        "cooldown_minutes": record.cooldown_minutes,
        "enabled": record.enabled,
        "revision": record.revision,
        "timezone": record.timezone,
        "next_occurrence": rfc3339(record.next_occurrence),
        "last_triggered_at": rfc3339(record.last_triggered_at),
        "last_acknowledged_at": rfc3339(record.last_acknowledged_at),
        "related_public_id": record.related_public_id,
        "source": record.source,
        "requires_device_confirmation": record.requires_device_confirmation,
        "created_at": rfc3339(record.created_at),
        "updated_at": rfc3339(record.updated_at),
    }


def list_rules(user_id: int) -> list[dict]:
    rows = db.session.execute(
        db.select(ReminderRule).options(selectinload(ReminderRule.goal)).where(
            ReminderRule.user_id == user_id
        ).order_by(ReminderRule.created_at, ReminderRule.public_id)
    ).scalars().all()
    return [serialize_rule(row) for row in rows]


def owned_rule(user_id: int, public_id: str, *, lock=False) -> ReminderRule:
    statement = db.select(ReminderRule).options(selectinload(ReminderRule.goal)).where(
        ReminderRule.user_id == user_id, ReminderRule.public_id == _uuid(public_id)
    )
    if lock:
        statement = statement.with_for_update()
    row = db.session.execute(statement).scalar_one_or_none()
    if row is None:
        raise MobileSyncError("not_found", "Recordatorio no encontrado.", 404)
    return row


def _recalculate_rule(row: ReminderRule) -> None:
    row.next_occurrence = (
        next_occurrence(row.local_time, row.applicable_days_json or [], row.timezone, row.lead_minutes)
        if row.enabled and not row.requires_device_confirmation else None
    )


def create_rule(user_id: int, payload: dict) -> ReminderRule:
    values = _rule_values(payload, user_id, creating=True)
    public_id = _uuid(payload.get("public_id") or uuid.uuid4())
    if db.session.execute(db.select(ReminderRule.id).where(ReminderRule.public_id == public_id)).scalar_one_or_none():
        raise MobileSyncError("conflict", "El identificador ya existe.", 409)
    row = ReminderRule(public_id=public_id, user_id=user_id, source="manual", **values)
    _recalculate_rule(row)
    db.session.add(row)
    db.session.flush()
    return row


def patch_rule(user_id: int, public_id: str, payload: dict) -> ReminderRule:
    row = owned_rule(user_id, public_id, lock=True)
    _revision(row.revision, payload.get("base_revision"))
    values = _rule_values(payload, user_id, creating=False)
    for key, value in values.items():
        setattr(row, key, value)
    row.requires_device_confirmation = False
    row.revision += 1
    row.updated_at = utcnow()
    _recalculate_rule(row)
    db.session.flush()
    return row


def delete_rule(user_id: int, public_id: str, payload: dict) -> dict:
    row = owned_rule(user_id, public_id, lock=True)
    if set(payload) != {"base_revision"}:
        raise MobileSyncError("invalid_request", "Se requiere únicamente base_revision.")
    _revision(row.revision, payload["base_revision"])
    result = {"public_id": row.public_id, "deleted": True, "revision": row.revision + 1}
    db.session.delete(row)
    db.session.flush()
    return result


def _event_key(user: User, rule: ReminderRule, scheduled_local: str, event_type: str, related: str | None) -> str:
    canonical = "|".join((user.public_id, rule.public_id, scheduled_local, event_type, related or ""))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def serialize_event(record: ReminderEvent) -> dict:
    return {
        "public_id": record.public_id,
        "rule_public_id": record.rule.public_id,
        "scheduled_for": rfc3339(record.scheduled_for),
        "scheduled_local": record.scheduled_local,
        "event_type": record.event_type,
        "related_public_id": record.related_public_id,
        "triggered_at": rfc3339(record.triggered_at),
        "state": record.state,
        "acknowledged_at": rfc3339(record.acknowledged_at),
        "snoozed_until": rfc3339(record.snoozed_until),
        "dismissed_at": rfc3339(record.dismissed_at),
        "deduplication_fingerprint": record.deduplication_key[:12],
        "error_code": record.error_code,
        "revision": record.revision,
        "created_at": rfc3339(record.created_at),
        "updated_at": rfc3339(record.updated_at),
    }


def create_event(user: User, payload: dict) -> tuple[ReminderEvent, bool]:
    allowed = {"public_id", "rule_public_id", "scheduled_for", "scheduled_local", "event_type", "related_public_id", "triggered_at", "state"}
    if set(payload) - allowed or not {"rule_public_id", "scheduled_for", "scheduled_local", "event_type"} <= set(payload):
        raise MobileSyncError("invalid_request", "El evento técnico no es válido.")
    rule = owned_rule(user.id, payload["rule_public_id"], lock=True)
    event_type = payload["event_type"]
    if event_type != rule.reminder_type:
        raise MobileSyncError("invalid_event_type", "El tipo del evento no coincide con la regla.")
    scheduled_for = _aware_datetime(payload["scheduled_for"], "scheduled_for")
    scheduled_local = str(payload["scheduled_local"])
    try:
        datetime.fromisoformat(scheduled_local)
    except ValueError as error:
        raise MobileSyncError("invalid_datetime", "scheduled_local no es válido.") from error
    related = None if payload.get("related_public_id") in (None, "") else _uuid(payload["related_public_id"], "related_public_id")
    key = _event_key(user, rule, scheduled_local, event_type, related)
    existing = db.session.execute(db.select(ReminderEvent).options(selectinload(ReminderEvent.rule)).where(
        ReminderEvent.user_id == user.id, ReminderEvent.deduplication_key == key
    )).scalar_one_or_none()
    if existing:
        return existing, True
    state = payload.get("state", "triggered")
    if state not in {"scheduled", "triggered", "suppressed", "cancelled", "failed"}:
        raise MobileSyncError("invalid_state", "El estado inicial del evento no es válido.")
    row = ReminderEvent(
        public_id=_uuid(payload.get("public_id") or uuid.uuid4()), user_id=user.id,
        rule_id=rule.id, scheduled_for=scheduled_for, scheduled_local=scheduled_local,
        event_type=event_type, related_public_id=related,
        triggered_at=_aware_datetime(payload["triggered_at"], "triggered_at") if payload.get("triggered_at") else (utcnow() if state == "triggered" else None),
        state=state, deduplication_key=key,
    )
    db.session.add(row)
    rule.last_triggered_at = row.triggered_at or rule.last_triggered_at
    db.session.flush()
    return row, False


def _aware_datetime(value, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise MobileSyncError("invalid_datetime", f"{field} debe ser RFC3339.") from error
    if parsed.tzinfo is None:
        raise MobileSyncError("invalid_datetime", f"{field} debe incluir offset.")
    return parsed.astimezone(timezone.utc)


def list_events(user_id: int, *, limit=50) -> list[dict]:
    if not 1 <= limit <= 100:
        raise MobileSyncError("invalid_limit", "El límite debe estar entre 1 y 100.")
    rows = db.session.execute(db.select(ReminderEvent).options(selectinload(ReminderEvent.rule)).where(
        ReminderEvent.user_id == user_id
    ).order_by(ReminderEvent.scheduled_for.desc(), ReminderEvent.public_id).limit(limit)).scalars().all()
    return [serialize_event(row) for row in rows]


def update_event(user_id: int, public_id: str, payload: dict) -> ReminderEvent:
    if set(payload) - {"base_revision", "action", "snoozed_until"}:
        raise MobileSyncError("invalid_request", "La acción del evento contiene campos no reconocidos.")
    row = db.session.execute(db.select(ReminderEvent).options(selectinload(ReminderEvent.rule)).where(
        ReminderEvent.user_id == user_id, ReminderEvent.public_id == _uuid(public_id)
    ).with_for_update()).scalar_one_or_none()
    if row is None:
        raise MobileSyncError("not_found", "Evento no encontrado.", 404)
    _revision(row.revision, payload.get("base_revision"))
    action = payload.get("action")
    now = utcnow()
    if action == "acknowledge":
        row.state = "acknowledged"; row.acknowledged_at = now
        row.rule.last_acknowledged_at = now
    elif action == "dismiss":
        row.state = "dismissed"; row.dismissed_at = now
    elif action == "snooze":
        until = _aware_datetime(payload.get("snoozed_until"), "snoozed_until")
        if until <= now or until > now + timedelta(days=7):
            raise MobileSyncError("invalid_snooze", "La posposición está fuera del intervalo permitido.")
        row.state = "snoozed"; row.snoozed_until = until
    else:
        raise MobileSyncError("invalid_action", "La acción del evento no está soportada.")
    row.revision += 1; row.updated_at = now
    db.session.flush()
    return row


def _eligible_days(goal: UserGoal, start: date, end: date) -> list[date]:
    effective_start = max(start, goal.start_date)
    effective_end = min(end, goal.end_date) if goal.end_date else end
    if effective_end < effective_start:
        return []
    selected = set(goal.applicable_days_json or range(1, 8))
    return [effective_start + timedelta(days=index) for index in range((effective_end - effective_start).days + 1)
            if (effective_start + timedelta(days=index)).isoweekday() in selected]


def _local_session_dates(rows: list[TrainingSession], timezone_name: str) -> list[date]:
    zone = ZoneInfo(timezone_name)
    dates = []
    seen = set()
    for row in rows:
        if row.public_id in seen:
            continue
        seen.add(row.public_id)
        value = row.completed_at or row.performed_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        dates.append(value.astimezone(zone).date())
    return dates


def _goal_counts(goal: UserGoal, start: date, end: date, data: dict) -> tuple[int, int, dict]:
    days = _eligible_days(goal, start, end)
    day_set = set(days)
    target = int(goal.target_value)
    details = {"eligible_days": len(days)}
    if not days:
        return 0, 0, details
    if goal.goal_type == "training_sessions_per_week":
        session_dates = [value for value in _local_session_dates(data["sessions"], goal.timezone) if value in day_set]
        return len(session_dates), target * math.ceil(len(days) / 7), details
    if goal.goal_type == "active_days_per_week":
        active = set(_local_session_dates(data["sessions"], goal.timezone)) & day_set
        return len(active), target * math.ceil(len(days) / 7), details
    if goal.goal_type == "active_plan_tracking":
        rows = [row for row in data["sessions"] if row.training_plan and row.training_plan.public_id == goal.related_public_id]
        count = sum(value in day_set for value in _local_session_dates(rows, goal.timezone))
        return count, target * math.ceil(len(days) / 7), details
    if goal.goal_type == "scheduled_workouts_completion":
        rows = [row for row in data["planned"] if row.scheduled_for_date in day_set]
        return sum(row.status == "completed" or row.completed_session is not None for row in rows), len(rows), details
    if goal.goal_type == "daily_steps":
        effective = {}
        for row in data["energy"]:
            if row.date not in day_set:
                continue
            current = effective.get(row.date)
            if current is None or row.source == "manual":
                effective[row.date] = row
        return sum(row.steps is not None and row.steps >= goal.target_value for row in effective.values()), len(days), details
    if goal.goal_type.startswith("nutrition_"):
        field = {
            "nutrition_calories": "calories", "nutrition_protein": "protein_g",
            "nutrition_carbohydrates": "total_carbs_g", "nutrition_fat": "fat_g",
        }[goal.goal_type]
        completed = 0
        for row in data["nutrition"]:
            if row.date not in day_set:
                continue
            value = getattr(row, field)
            if field == "total_carbs_g" and value is None:
                value = row.net_carbs_g
            completed += value is not None and value >= goal.target_value
        return completed, len(days), details
    if goal.goal_type == "weight_logging_frequency":
        zone = ZoneInfo(goal.timezone)
        recorded = set()
        for row in data["weights"]:
            value = row.recorded_at
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            recorded.add(value.astimezone(zone).date())
        expected = len(days) if goal.period in {"daily", "selected_days"} else target * math.ceil(len(days) / 7)
        return len(recorded & day_set), expected, details
    return 0, 0, details


def _status(goal: UserGoal, completed: int, expected: int, start: date, end: date, today: date) -> str:
    if goal.state == "paused":
        return "paused"
    if expected <= 0:
        return "insufficient_data"
    if completed >= expected:
        return "completed"
    if end < today and completed == 0:
        return "missed"
    elapsed = max(1, min((today - start).days + 1, (end - start).days + 1))
    expected_ratio = elapsed / max(1, (end - start).days + 1)
    return "on_track" if completed / expected >= expected_ratio else "partially_complete"


def _summary_text(status: str, completed: int, expected: int) -> str:
    if expected <= 0:
        return "Sin datos suficientes"
    if status == "paused":
        return "Objetivo en pausa"
    if completed >= expected:
        return f"{completed} de {expected} completados"
    remaining = expected - completed
    return f"{completed} de {expected}; queda {remaining} en este periodo"


def _load_adherence_data(user_id: int, start: date, end: date) -> dict:
    start_at = datetime.combine(start - timedelta(days=1), time.min, timezone.utc)
    end_at = datetime.combine(end + timedelta(days=2), time.min, timezone.utc)
    return {
        "sessions": db.session.execute(db.select(TrainingSession).options(selectinload(TrainingSession.training_plan)).where(
            TrainingSession.user_id == user_id, TrainingSession.deleted_at.is_(None),
            TrainingSession.performed_at >= start_at, TrainingSession.performed_at < end_at,
        )).scalars().all(),
        "planned": db.session.execute(db.select(PlannedWorkout).options(selectinload(PlannedWorkout.completed_session)).where(
            PlannedWorkout.user_id == user_id, PlannedWorkout.deleted_at.is_(None),
            PlannedWorkout.scheduled_for_date.between(start, end),
        )).scalars().all(),
        "energy": db.session.execute(db.select(DailyEnergy).where(
            DailyEnergy.user_id == user_id, DailyEnergy.date.between(start, end)
        )).scalars().all(),
        "nutrition": db.session.execute(db.select(DailyNutrition).where(
            DailyNutrition.user_id == user_id, DailyNutrition.date.between(start, end)
        )).scalars().all(),
        "weights": db.session.execute(db.select(WeighIn).where(
            WeighIn.user_id == user_id, WeighIn.recorded_at >= start_at,
            WeighIn.recorded_at < end_at,
        )).scalars().all(),
    }


def adherence_summary(user: User, *, days: int, end: date | None = None, timezone_name: str | None = None) -> dict:
    if days not in {7, 30, 90}:
        raise MobileSyncError("invalid_range", "El periodo debe ser 7, 30 o 90 días.")
    timezone_name = validate_timezone(timezone_name or user.timezone or "UTC")
    today = datetime.now(ZoneInfo(timezone_name)).date()
    end = end or today
    start = end - timedelta(days=days - 1)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    goals = db.session.execute(db.select(UserGoal).where(
        UserGoal.user_id == user.id, UserGoal.state != "archived",
        UserGoal.start_date <= end,
        db.or_(UserGoal.end_date.is_(None), UserGoal.end_date >= previous_start),
    ).order_by(UserGoal.created_at, UserGoal.public_id)).scalars().all()
    if not goals:
        return {"period": {"from": start.isoformat(), "to": end.isoformat(), "days": days, "timezone": timezone_name},
                "status": "no_configured", "items": [], "summary": "No hay objetivos configurados."}
    data = _load_adherence_data(user.id, previous_start, end)
    items = []
    for goal in goals:
        completed, expected, details = _goal_counts(goal, start, end, data)
        previous_completed, previous_expected, _ = _goal_counts(goal, previous_start, previous_end, data)
        status = _status(goal, completed, expected, start, end, today)
        percentage = min(100.0, round(completed * 100 / expected, 2)) if expected > 0 else None
        previous_percentage = min(100.0, round(previous_completed * 100 / previous_expected, 2)) if previous_expected > 0 else None
        items.append({
            "goal": serialize_goal(goal), "status": status, "completed": completed,
            "expected": expected, "percentage": percentage, "summary": _summary_text(status, completed, expected),
            "comparison": {
                "previous_completed": previous_completed, "previous_expected": previous_expected,
                "absolute_change": completed - previous_completed,
                "percentage_change": (
                    round((percentage - previous_percentage), 2)
                    if percentage is not None and previous_percentage is not None else None
                ),
            },
            "details": details,
        })
    return {"period": {"from": start.isoformat(), "to": end.isoformat(), "days": days, "timezone": timezone_name},
            "status": "available", "items": items,
            "summary": f"{len(items)} objetivo{'s' if len(items) != 1 else ''} en este periodo."}


def adherence_timeline(user: User, *, days: int, end: date | None = None, timezone_name: str | None = None) -> dict:
    summary = adherence_summary(user, days=days, end=end, timezone_name=timezone_name)
    start = date.fromisoformat(summary["period"]["from"])
    finish = date.fromisoformat(summary["period"]["to"])
    points = []
    current = start
    while current <= finish:
        points.append({
            "date": current.isoformat(),
            "configured_goals": sum(
                item["goal"]["start_date"] <= current.isoformat()
                and (item["goal"]["end_date"] is None or item["goal"]["end_date"] >= current.isoformat())
                for item in summary["items"]
            ),
        })
        current += timedelta(days=1)
    return {"period": summary["period"], "status": summary["status"], "points": points}


def active_goal_targets(user_id: int, target_date: date) -> dict[str, UserGoal]:
    rows = db.session.execute(db.select(UserGoal).where(
        UserGoal.user_id == user_id, UserGoal.state == "active",
        UserGoal.start_date <= target_date,
        db.or_(UserGoal.end_date.is_(None), UserGoal.end_date >= target_date),
        UserGoal.goal_type.in_(("daily_steps", "nutrition_calories", "nutrition_protein", "nutrition_carbohydrates", "nutrition_fat")),
    ).order_by(UserGoal.updated_at.desc(), UserGoal.id.desc())).scalars().all()
    result = {}
    for row in rows:
        if target_date.isoweekday() in set(row.applicable_days_json or range(1, 8)):
            result.setdefault(row.goal_type, row)
    return result
