from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from jsonschema import Draft202012Validator

from app.extensions import db
from app.models import Activity, DailyEnergy, DailyNutrition, TrainingSession, User, WeighIn
from app.services.ai.types import (
    AIToolCapabilityMetadata,
    AIToolDefinition,
    AIToolExecution,
)
from app.services.dashboard.date_range import DashboardDateRange, DashboardRangeError
from app.services.dashboard.nutrition import NutritionTrendService
from app.services.dashboard.serializers import serialize_dashboard
from app.services.dashboard.summary import DashboardSummaryService
from app.services.dashboard.weight import WeightTrendService
from app.services.engagement import adherence_summary
from app.services.exercise_progress import ExerciseProgressService
from app.services.mobile_health import health_progress
from app.services.mobile_progress import history_page
from app.services.mobile_sync import MobileSyncError
from app.services.nutrition_patterns import NutritionPatternsService


PERIOD_PRESETS = (
    "today",
    "7d",
    "30d",
    "90d",
    "this-month",
    "previous-month",
)


class AIToolError(ValueError):
    def __init__(self, code: str, message: str, *, rejected: bool = False):
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.rejected = rejected


def _period_schema(*, comparison: bool = False) -> dict:
    properties = {"preset": {"type": "string", "enum": list(PERIOD_PRESETS)}}
    if comparison:
        properties["compare_previous"] = {"type": "boolean"}
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }


def _metadata(domains, entities, metrics, operations):
    return AIToolCapabilityMetadata(
        tuple(domains), tuple(entities), tuple(metrics), tuple(operations)
    )


def _today_override() -> date | None:
    value = current_app.config.get("AI_TODAY_OVERRIDE")
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise AIToolError("invalid_configuration", "La fecha AI de prueba no es válida.") from error


def _timezone(user: User) -> str:
    timezone_name = user.timezone or current_app.config["APP_TIMEZONE"]
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise AIToolError(
            "invalid_timezone",
            "La zona horaria de la cuenta no es válida.",
        ) from error
    return timezone_name


def _date_range(user: User, arguments: dict, *, comparison: bool = False) -> DashboardDateRange:
    query = {"preset": arguments.get("preset", "30d")}
    if comparison and arguments.get("compare_previous"):
        query["compare"] = "previous"
    try:
        return DashboardDateRange.from_query(
            query,
            _timezone(user),
            today=_today_override(),
        )
    except DashboardRangeError as error:
        raise AIToolError("invalid_range", str(error)) from error


def _clean_text(value: str, maximum: int = 500) -> str:
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    return value[:maximum]


def sanitize_untrusted_data(value, *, depth: int = 0):
    """Bound imported/external values before they cross the provider boundary."""
    if depth > 8:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            _clean_text(str(key), 80): sanitize_untrusted_data(item, depth=depth + 1)
            for key, item in list(value.items())[:80]
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_untrusted_data(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return _clean_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _clean_text(str(value))


def _source_category(source: str) -> tuple[str, str]:
    normalized = source.casefold().replace("-", "_")
    if "health_connect" in normalized:
        return "health_connect", "imported"
    if normalized in {"manual", "manual_generated", "user_override"}:
        return "manual", "recorded"
    if "device" in normalized or normalized == "synced_from_device":
        return "device", "imported"
    if any(
        token in normalized
        for token in ("import", "upload", "fit", "gpx", "tcx", "csv", "converted")
    ):
        return "import", "imported"
    if normalized.startswith("external") or normalized in {
        "strava",
        "garmin",
        "trainingpeaks",
    }:
        return "external_provider", "imported"
    return "other", "recorded"


def _source_item(metric: str, source: str, count: int, period: dict) -> dict:
    category, evidence_kind = _source_category(source)
    item = {
        "metric": metric,
        "period": period,
        "source": _clean_text(source, 128),
        "source_category": category,
        "evidence_kind": evidence_kind,
        "records": count,
    }
    if category == "external_provider":
        item.update(
            {
                "source_type": "external_provider",
                "provider": _clean_text(source, 128),
                "resource_type": "activity" if metric == "activities" else metric,
            }
        )
    return item


class AIProvenanceService:
    """Read only source metadata; raw health payloads never cross this boundary."""

    def for_domains(
        self,
        user_id: int,
        date_range: DashboardDateRange,
        domains: tuple[str, ...],
    ) -> list[dict]:
        period = {
            "from": date_range.start_date.isoformat(),
            "to": date_range.end_date.isoformat(),
            "timezone": date_range.timezone,
        }
        evidence: list[dict] = []
        if "weight" in domains:
            start_at, end_at = date_range.utc_bounds()
            rows = db.session.execute(
                db.select(WeighIn.source, db.func.count(WeighIn.id))
                .where(
                    WeighIn.user_id == user_id,
                    WeighIn.recorded_at >= start_at,
                    WeighIn.recorded_at < end_at,
                )
                .group_by(WeighIn.source)
            ).all()
            evidence.extend(_source_item("weight", source, count, period) for source, count in rows)
        if "nutrition" in domains:
            nutrition_rows = db.session.execute(
                db.select(DailyNutrition.source, db.func.count(DailyNutrition.id))
                .where(
                    DailyNutrition.user_id == user_id,
                    DailyNutrition.date.between(
                        date_range.start_date, date_range.end_date
                    ),
                )
                .group_by(DailyNutrition.source)
            ).all()
            evidence.extend(
                _source_item("nutrition", source, count, period)
                for source, count in nutrition_rows
            )
        if "steps" in domains:
            step_rows = db.session.execute(
                db.select(DailyEnergy.source, db.func.count(DailyEnergy.id))
                .where(
                    DailyEnergy.user_id == user_id,
                    DailyEnergy.date.between(
                        date_range.start_date, date_range.end_date
                    ),
                    DailyEnergy.steps.is_not(None),
                )
                .group_by(DailyEnergy.source)
            ).all()
            evidence.extend(
                _source_item("steps", source, count, period)
                for source, count in step_rows
            )
        if "training" in domains:
            start_at, end_at = date_range.utc_bounds()
            sessions = db.session.execute(
                db.select(
                    TrainingSession.source_file_id,
                    TrainingSession.source_device_id,
                ).where(
                    TrainingSession.user_id == user_id,
                    TrainingSession.deleted_at.is_(None),
                    TrainingSession.performed_at >= start_at,
                    TrainingSession.performed_at < end_at,
                )
            ).all()
            counts = Counter(
                "device_sync"
                if source_device_id is not None
                else "import"
                if source_file_id is not None
                else "manual"
                for source_file_id, source_device_id in sessions
            )
            evidence.extend(
                _source_item("training", source, count, period)
                for source, count in counts.items()
            )
        if "activities" in domains:
            start_at, end_at = date_range.utc_bounds()
            activities = db.session.execute(
                db.select(
                    Activity.source_type,
                    Activity.source_app,
                    Activity.source_format,
                ).where(
                    Activity.user_id == user_id,
                    Activity.started_at >= start_at,
                    Activity.started_at < end_at,
                )
            ).all()
            counts = Counter(
                (source_app or source_format or source_type or "unknown")
                for source_type, source_app, source_format in activities
            )
            evidence.extend(
                _source_item("activities", source, count, period)
                for source, count in counts.items()
            )
        return evidence


def _calculated_evidence(metric: str, period: dict) -> dict:
    return {
        "metric": metric,
        "period": {
            "from": period.get("from"),
            "to": period.get("to"),
            "timezone": period.get("timezone"),
        },
        "source": "health_tracker",
        "source_category": "calculation",
        "evidence_kind": "calculated",
    }


def _dashboard(user: User, arguments: dict) -> AIToolExecution:
    date_range = _date_range(user, arguments, comparison=True)
    result = DashboardSummaryService().build(
        user.id, date_range, user.preferred_load_unit
    )
    evidence = AIProvenanceService().for_domains(
        user.id,
        date_range,
        ("weight", "nutrition", "steps", "training"),
    )
    evidence.append(_calculated_evidence("dashboard_summary", result["range"]))
    data = {
        "period": result["range"],
        "metrics": result["summary"],
        "coverage": result["coverage"],
        "comparison": {
            "range": result.get("comparison", {}).get("range"),
            "available": result.get("comparison", {}).get("available", False),
            "rows": result.get("comparison", {}).get("rows", []),
        },
        "sources": evidence,
    }
    return AIToolExecution(sanitize_untrusted_data(data), tuple(evidence))


def _weight(user: User, arguments: dict) -> AIToolExecution:
    date_range = _date_range(user, arguments, comparison=True)
    result = serialize_dashboard(
        WeightTrendService().build(
            user.id, date_range, user.preferred_load_unit
        )
    )
    evidence = AIProvenanceService().for_domains(user.id, date_range, ("weight",))
    evidence.append(_calculated_evidence("weight_trend", date_range.as_dict()))
    comparison = None
    if date_range.compare_previous:
        previous_range = date_range.previous_period()
        previous = serialize_dashboard(
            WeightTrendService().build(
                user.id, previous_range, user.preferred_load_unit
            )
        )
        comparison = {
            "period": previous_range.as_dict(),
            "metrics": previous["summary"],
            "coverage": previous["coverage"],
        }
    data = {
        "period": date_range.as_dict(),
        "metrics": result["summary"],
        "coverage": result["coverage"],
        "points": result["trend"][-30:],
        "comparison": comparison,
        "sources": evidence,
    }
    return AIToolExecution(sanitize_untrusted_data(data), tuple(evidence))


def _latest_body_measurement(user: User, arguments: dict) -> AIToolExecution:
    timezone_name = _timezone(user)
    zone = ZoneInfo(timezone_name)
    requested_date = arguments.get("date")
    match = arguments.get("match")
    if match is not None and requested_date is None:
        raise AIToolError(
            "invalid_tool_arguments",
            "match requiere una fecha explícita.",
            rejected=True,
        )

    statement = db.select(WeighIn).where(WeighIn.user_id == user.id)
    if requested_date is None:
        period = {"kind": "latest_available", "timezone": timezone_name}
    else:
        try:
            target_date = date.fromisoformat(requested_date)
        except (TypeError, ValueError) as error:
            raise AIToolError(
                "invalid_tool_arguments",
                "La fecha solicitada debe usar YYYY-MM-DD.",
                rejected=True,
            ) from error
        start_at = datetime.combine(target_date, time.min, zone).astimezone(timezone.utc)
        end_at = datetime.combine(
            target_date + timedelta(days=1), time.min, zone
        ).astimezone(timezone.utc)
        if match == "on_or_before":
            statement = statement.where(WeighIn.recorded_at < end_at)
            period = {
                "kind": "latest_on_or_before",
                "date": target_date.isoformat(),
                "timezone": timezone_name,
            }
        else:
            statement = statement.where(
                WeighIn.recorded_at >= start_at,
                WeighIn.recorded_at < end_at,
            )
            period = {
                "kind": "exact_date",
                "date": target_date.isoformat(),
                "timezone": timezone_name,
            }

    record = db.session.execute(
        statement.order_by(WeighIn.recorded_at.desc(), WeighIn.id.desc()).limit(1)
    ).scalar_one_or_none()
    metric_names = (
        "weight_kg",
        "body_fat_percent",
        "muscle_mass_kg",
        "water_percent",
        "visceral_fat",
        "bmr_kcal",
        "bmi",
    )
    if record is None:
        metrics = {name: None for name in metric_names}
        metrics.update({"recorded_at": None, "local_date": None})
        evidence: tuple[dict, ...] = ()
    else:
        recorded_at = record.recorded_at
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        else:
            recorded_at = recorded_at.astimezone(timezone.utc)
        metrics = {
            "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
            "local_date": recorded_at.astimezone(zone).date().isoformat(),
            "weight_kg": record.weight_kg,
            "body_fat_percent": record.body_fat_percentage,
            "muscle_mass_kg": record.muscle_mass_kg,
            "water_percent": record.water_percentage,
            "visceral_fat": record.visceral_fat,
            "bmr_kcal": record.bmr_kcal,
            "bmi": record.bmi,
        }
        source = _source_item("body_measurement", record.source, 1, period)
        evidence = (source,)
    data = {
        "period": period,
        "metrics": metrics,
        "coverage": {"body_measurements": 1 if record is not None else 0},
        "sources": list(evidence),
    }
    return AIToolExecution(sanitize_untrusted_data(data), evidence)


def _nutrition(user: User, arguments: dict) -> AIToolExecution:
    date_range = _date_range(user, arguments, comparison=True)
    result = serialize_dashboard(NutritionTrendService().build(user.id, date_range))
    evidence = AIProvenanceService().for_domains(user.id, date_range, ("nutrition",))
    evidence.append(_calculated_evidence("nutrition_summary", date_range.as_dict()))
    comparison = None
    if date_range.compare_previous:
        previous_range = date_range.previous_period()
        previous = serialize_dashboard(
            NutritionTrendService().build(user.id, previous_range)
        )
        comparison = {
            "period": previous_range.as_dict(),
            "metrics": previous["summary"],
            "coverage": previous["coverage"],
        }
    data = {
        "period": date_range.as_dict(),
        "metrics": result["summary"],
        "coverage": result["coverage"],
        "comparison": comparison,
        "sources": evidence,
    }
    return AIToolExecution(sanitize_untrusted_data(data), tuple(evidence))


def _food_patterns(user: User, arguments: dict) -> AIToolExecution:
    date_range = _date_range(user, arguments)
    result = NutritionPatternsService().build(user.id, date_range)
    evidence = AIProvenanceService().for_domains(user.id, date_range, ("nutrition",))
    evidence.append(_calculated_evidence("food_patterns", date_range.as_dict()))
    result["sources"] = evidence
    return AIToolExecution(sanitize_untrusted_data(result), tuple(evidence))


def _training(user: User, arguments: dict) -> AIToolExecution:
    date_range = _date_range(user, arguments, comparison=True)
    result = DashboardSummaryService().build(
        user.id, date_range, user.preferred_load_unit
    )
    comparison_rows = result.get("comparison", {}).get("rows", [])[-5:]
    evidence = AIProvenanceService().for_domains(user.id, date_range, ("training",))
    evidence.append(_calculated_evidence("training_summary", result["range"]))
    data = {
        "period": result["range"],
        "metrics": result["summary"]["training"],
        "coverage": {
            key: value
            for key, value in result["coverage"].items()
            if key.startswith("training") or key == "planned_workouts"
        },
        "comparison": {
            "range": result.get("comparison", {}).get("range"),
            "available": result.get("comparison", {}).get("available", False),
            "rows": comparison_rows,
        },
        "sources": evidence,
    }
    return AIToolExecution(sanitize_untrusted_data(data), tuple(evidence))


def _training_history(user: User, arguments: dict) -> AIToolExecution:
    limit = arguments.get("limit", 10)
    try:
        result = history_page(user_id=user.id, limit=limit)
    except MobileSyncError as error:
        raise AIToolError("invalid_tool_arguments", str(error)) from error
    sources = Counter(item.get("source") or "unknown" for item in result["items"])
    period = {"kind": "recent", "timezone": _timezone(user)}
    evidence = tuple(
        _source_item("training_history", source, count, period)
        for source, count in sources.items()
    )
    data = {
        "period": period,
        "metrics": {"count": len(result["items"]), "has_more": result["has_more"]},
        "items": result["items"],
        "coverage": {"returned": len(result["items"]), "limit": limit},
        "sources": list(evidence),
    }
    return AIToolExecution(sanitize_untrusted_data(data), evidence)


def _exercise_progress(user: User, arguments: dict) -> AIToolExecution:
    preset = arguments.get("preset", "30d")
    exercise = arguments.get("exercise")
    limit = arguments.get("limit", 8)
    try:
        result = ExerciseProgressService().build(
            user.id,
            preset,
            exercise=exercise,
            limit=limit,
        )
    except MobileSyncError as error:
        raise AIToolError("invalid_tool_arguments", str(error)) from error
    date_range = _date_range(user, {"preset": preset})
    evidence = AIProvenanceService().for_domains(user.id, date_range, ("training",))
    evidence.append(_calculated_evidence("exercise_progress", date_range.as_dict()))
    result["sources"] = evidence
    return AIToolExecution(sanitize_untrusted_data(result), tuple(evidence))


def _activities(user: User, arguments: dict) -> AIToolExecution:
    from app.api_v1.errors import ApiError
    from app.services.activity_interchange import list_activities

    limit = arguments.get("limit", 10)
    try:
        result = list_activities(user.id, limit=limit)
    except ApiError as error:
        raise AIToolError(error.code, error.message) from error
    sources = Counter(
        (item.get("sourceApplication") or item.get("sourceFormat") or "unknown")
        for item in result["items"]
    )
    items = [
        {
            key: item[key]
            for key in (
                "discipline",
                "subtype",
                "title",
                "startTime",
                "endTime",
                "localDate",
                "environment",
                "status",
                "sourceFormat",
                "sourceApplication",
                "summary",
                "lapCount",
                "sampleCount",
            )
            if key in item
        }
        for item in result["items"]
    ]
    period = {"kind": "recent", "timezone": _timezone(user)}
    evidence = tuple(
        _source_item("activities", source, count, period)
        for source, count in sources.items()
    )
    data = {
        "period": period,
        "metrics": {"count": len(result["items"]), "has_more": bool(result["next_cursor"])},
        "items": items,
        "coverage": {"returned": len(result["items"]), "limit": limit},
        "sources": list(evidence),
    }
    return AIToolExecution(sanitize_untrusted_data(data), evidence)


def _steps(user: User, arguments: dict) -> AIToolExecution:
    date_range = _date_range(user, arguments)
    try:
        progress = health_progress(
            user.id,
            date_range.start_date,
            date_range.end_date,
            date_range.timezone,
        )
    except MobileSyncError as error:
        raise AIToolError("invalid_range", str(error)) from error
    points = [point for point in progress["points"] if point.get("steps") is not None]
    total = sum(point["steps"] for point in points) if points else None
    evidence = AIProvenanceService().for_domains(user.id, date_range, ("steps",))
    evidence.append(_calculated_evidence("steps_summary", date_range.as_dict()))
    data = {
        "period": date_range.as_dict(),
        "metrics": {
            "total": total,
            "average": round(total / len(points), 2) if total is not None else None,
            "days_with_data": len(points),
        },
        "coverage": {
            "period_days": date_range.days,
            "days_with_data": len(points),
        },
        "points": [
            {
                "date": point["date"],
                "steps": point["steps"],
                "source": point.get("steps_source"),
            }
            for point in points
        ],
        "sources": evidence,
    }
    return AIToolExecution(sanitize_untrusted_data(data), tuple(evidence))


def _goals(user: User, arguments: dict) -> AIToolExecution:
    days = arguments.get("days", 30)
    try:
        result = adherence_summary(
            user,
            days=days,
            timezone_name=_timezone(user),
            end=_today_override(),
        )
    except MobileSyncError as error:
        raise AIToolError("invalid_tool_arguments", str(error)) from error
    evidence = tuple(
        {
            "metric": item["goal"]["goal_type"],
            "period": result["period"],
            "source": item["goal"].get("source") or "manual",
            "source_category": _source_category(item["goal"].get("source") or "manual")[0],
            "evidence_kind": "calculated",
        }
        for item in result["items"]
    )
    data = {
        "period": result["period"],
        "metrics": {"count": len(result["items"]), "status": result["status"]},
        "items": result["items"],
        "coverage": {"goals": len(result["items"])},
        "summary": result["summary"],
        "sources": list(evidence),
    }
    return AIToolExecution(sanitize_untrusted_data(data), evidence)


def _data_sources(user: User, arguments: dict) -> AIToolExecution:
    date_range = _date_range(user, arguments)
    domain = arguments.get("domain", "all")
    domain_map = {
        "all": ("weight", "nutrition", "steps", "training", "activities"),
        "weight": ("weight",),
        "nutrition": ("nutrition",),
        "steps": ("steps",),
        "training": ("training",),
        "activities": ("activities",),
    }
    evidence = AIProvenanceService().for_domains(
        user.id, date_range, domain_map[domain]
    )
    data = {
        "period": date_range.as_dict(),
        "metrics": {"source_count": len(evidence), "domain": domain},
        "coverage": {"records": sum(item["records"] for item in evidence)},
        "sources": evidence,
    }
    return AIToolExecution(sanitize_untrusted_data(data), tuple(evidence))


class AIToolRegistry:
    def __init__(self):
        self._handlers: dict[str, tuple[AIToolDefinition, Callable[[User, dict], AIToolExecution]]] = {}
        self._register(
            "get_dashboard_summary",
            "Resumen longitudinal de energía, proteína, peso y entrenamiento.",
            _period_schema(comparison=True),
            _dashboard,
            _metadata(
                ("all", "energy", "data"),
                ("dashboard_summary",),
                ("balance", "intake", "expenditure", "coverage"),
                ("summary", "trend", "compare", "coverage"),
            ),
        )
        self._register(
            "get_weight_trend",
            "Tendencia owner-only de peso para cambios, promedios o periodos; no usar para una medición puntual.",
            _period_schema(comparison=True),
            _weight,
            _metadata(
                ("body",),
                ("body_measurement",),
                ("weight", "body_fat", "muscle_mass", "body_water", "visceral_fat", "bmi", "bmr"),
                ("summary", "trend", "compare", "coverage"),
            ),
        )
        self._register(
            "get_latest_body_measurement",
            (
                "Medición corporal puntual owner-only. Sin argumentos devuelve la última "
                "disponible sin límite temporal; date+exact busca ese día local y "
                "date+on_or_before devuelve la última hasta ese día. Incluye peso y "
                "todas las métricas de composición soportadas, zona horaria y procedencia."
            ),
            {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "format": "date"},
                    "match": {
                        "type": "string",
                        "enum": ["exact", "on_or_before"],
                    },
                },
                "additionalProperties": False,
            },
            _latest_body_measurement,
            _metadata(
                ("body",),
                ("body_measurement",),
                ("weight", "body_fat", "muscle_mass", "body_water", "visceral_fat", "bmi", "bmr"),
                ("latest", "summary"),
            ),
        )
        self._register(
            "get_nutrition_summary",
            "Resumen owner-only de nutrición y proteína.",
            _period_schema(comparison=True),
            _nutrition,
            _metadata(
                ("nutrition",),
                ("daily_nutrition",),
                ("calories", "protein", "fat", "net_carbs", "total_carbs", "fiber", "sugar", "sodium"),
                ("summary", "trend", "compare", "consistency", "coverage"),
            ),
        )
        self._register(
            "get_food_patterns",
            "Patrones agregados owner-only de registros, comidas, nombres y cobertura; sin inferencias clínicas.",
            _period_schema(),
            _food_patterns,
            _metadata(
                ("nutrition",),
                ("food_entry", "daily_nutrition"),
                ("food_entries",),
                ("patterns", "coverage"),
            ),
        )
        self._register(
            "get_training_summary",
            "Resumen owner-only de entrenamiento y comparación opcional.",
            _period_schema(comparison=True),
            _training,
            _metadata(
                ("training",),
                ("training_session",),
                ("sessions", "duration", "volume"),
                ("summary", "compare", "consistency", "coverage"),
            ),
        )
        self._register(
            "get_training_history",
            "Historial reciente y acotado de sesiones de entrenamiento.",
            {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
                "additionalProperties": False,
            },
            _training_history,
            _metadata(
                ("training",),
                ("training_session",),
                ("sessions",),
                ("latest",),
            ),
        )
        self._register(
            "get_exercise_progress",
            "Progreso owner-only por ejercicio con sesiones, sets y cargas únicamente comparables.",
            {
                "type": "object",
                "properties": {
                    "preset": {"type": "string", "enum": ["7d", "30d", "90d"]},
                    "exercise": {"type": "string", "minLength": 1, "maxLength": 200},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "additionalProperties": False,
            },
            _exercise_progress,
            _metadata(
                ("training",),
                ("exercise", "training_session", "training_set"),
                ("exercise_load", "volume", "reps"),
                ("trend", "progress"),
            ),
        )
        self._register(
            "get_activity_summary",
            "Actividades recientes normalizadas sin rutas ni payloads crudos.",
            {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
                "additionalProperties": False,
            },
            _activities,
            _metadata(
                ("activity",),
                ("activity",),
                ("activity", "active_days"),
                ("summary", "consistency"),
            ),
        )
        self._register(
            "get_steps_summary",
            "Pasos efectivos por día sin sumar fuentes potencialmente solapadas.",
            _period_schema(),
            _steps,
            _metadata(
                ("activity",),
                ("daily_steps",),
                ("steps", "active_days"),
                ("summary", "trend", "progress", "consistency", "coverage"),
            ),
        )
        self._register(
            "get_goals_summary",
            "Objetivos y adherencia descriptiva, no clínica.",
            {
                "type": "object",
                "properties": {"days": {"type": "integer", "enum": [7, 30, 90]}},
                "additionalProperties": False,
            },
            _goals,
            _metadata(
                ("goals", "nutrition"),
                ("user_goal",),
                ("goals", "adherence", "protein", "fat", "net_carbs"),
                ("summary", "progress", "coverage", "compare"),
            ),
        )
        self._register(
            "get_data_sources_summary",
            "Procedencia de datos por dominio sin exponer archivos o payloads.",
            {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "enum": ["all", "weight", "nutrition", "steps", "training", "activities"],
                    },
                    "preset": {"type": "string", "enum": list(PERIOD_PRESETS)},
                },
                "additionalProperties": False,
            },
            _data_sources,
            _metadata(
                ("data", "nutrition", "activity", "training"),
                ("data_source",),
                ("coverage", "provenance"),
                ("summary", "coverage", "sources"),
            ),
        )

    def _register(
        self,
        name: str,
        description: str,
        schema: dict,
        handler: Callable,
        capability: AIToolCapabilityMetadata,
    ) -> None:
        self._handlers[name] = (
            AIToolDefinition(name, description, schema, capability),
            handler,
        )

    @property
    def definitions(self) -> tuple[AIToolDefinition, ...]:
        return tuple(definition for definition, _handler in self._handlers.values())

    def execute(self, user: User, name: str, arguments: dict) -> AIToolExecution:
        entry = self._handlers.get(name)
        if entry is None:
            raise AIToolError(
                "tool_not_allowed",
                "La herramienta solicitada no está autorizada.",
                rejected=True,
            )
        definition, handler = entry
        if not isinstance(arguments, dict):
            raise AIToolError(
                "invalid_tool_arguments",
                "Los argumentos de la herramienta no son válidos.",
                rejected=True,
            )
        errors = sorted(
            Draft202012Validator(definition.input_schema).iter_errors(arguments),
            key=lambda item: list(item.path),
        )
        if errors:
            raise AIToolError(
                "invalid_tool_arguments",
                "Los argumentos de la herramienta no cumplen el contrato permitido.",
                rejected=True,
            )
        return handler(user, dict(arguments))
