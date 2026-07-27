"""Owner-scoped mobile read models over the existing health domain tables."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (
    DailyEnergy,
    DailyNutrition,
    FoodProduct,
    NutritionItem,
    NutritionMeal,
    PlannedWorkout,
    WeighIn,
)
from app.services.daily_balance import effective_energy_record
from app.services.mobile_sync import MobileSyncError, rfc3339


LB_TO_KG = Decimal("0.45359237")
NUTRITION_FIELDS = (
    "calories",
    "protein_g",
    "fat_g",
    "net_carbs_g",
    "total_carbs_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
)
MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack", "extra", "other"}
BODY_SOURCES = {"manual", "health_connect", "user_override"}
NUTRITION_SOURCES = {"manual", "health_connect", "user_override"}
STEP_SOURCES = {"manual", "health_connect_aggregate"}


def _serializer(salt: str) -> URLSafeSerializer:
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=salt)


def _uuid(value, label: str = "El ID") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError) as error:
        raise MobileSyncError("invalid_id", f"{label} no es válido.") from error


def _text(value, *, field: str, maximum: int, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise MobileSyncError("invalid_request", f"{field} no es válido.")
    result = value.strip()
    if (required and not result) or len(result) > maximum:
        raise MobileSyncError("invalid_request", f"{field} no es válido.")
    return result or None


def _decimal(value, *, field: str, minimum=0, maximum=1_000_000) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise MobileSyncError("invalid_request", f"{field} no es válido.") from error
    if not result.is_finite() or result < Decimal(str(minimum)) or result > Decimal(str(maximum)):
        raise MobileSyncError("invalid_request", f"{field} está fuera de rango.")
    return result


def _integer(value, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise MobileSyncError("invalid_request", f"{field} está fuera de rango.")
    return value


def _date(value, field: str = "date") -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise MobileSyncError("invalid_date", f"{field} debe usar YYYY-MM-DD.") from error


def _timezone(value: str | None) -> ZoneInfo:
    name = value or current_app.config["APP_TIMEZONE"]
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
        raise MobileSyncError("invalid_timezone", "La zona horaria IANA no es válida.") from error


def _timestamp(value) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise MobileSyncError("invalid_datetime", "recorded_at debe ser ISO 8601.") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise MobileSyncError("invalid_datetime", "recorded_at debe incluir zona horaria.")
    return result.astimezone(timezone.utc)


def _number(value):
    return format(value.normalize(), "f") if isinstance(value, Decimal) else None


def _check_revision(current: int, supplied) -> None:
    if isinstance(supplied, bool) or not isinstance(supplied, int):
        raise MobileSyncError("invalid_request", "Se requiere base_revision.")
    if current != supplied:
        raise MobileSyncError(
            "revision_conflict",
            "El recurso cambió en el servidor.",
            409,
            {
                "server_revision": current,
                "conflict_code": "stale_revision",
                "resolution_options": ["keep_remote", "retry_local_copy", "duplicate_local_copy"],
            },
        )


def _day_bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    return start, end


def serialize_body_stat(record: WeighIn) -> dict:
    return {
        "id": record.public_id,
        "recorded_at": rfc3339(record.recorded_at),
        "weight_kg": _number(record.weight_kg),
        "body_fat_percent": _number(record.body_fat_percentage),
        "muscle_mass_kg": _number(record.muscle_mass_kg),
        "water_percent": _number(record.water_percentage),
        "visceral_fat": _number(record.visceral_fat),
        "bmr_kcal": _number(record.bmr_kcal),
        "bmi": _number(record.bmi),
        "notes": record.notes,
        "source": record.source,
        "client_event_id": record.client_event_id,
        "revision": record.revision,
        "created_at": rfc3339(record.created_at),
        "updated_at": rfc3339(record.updated_at),
    }


def _body_values(payload: dict, *, creating: bool) -> dict:
    allowed = {
        "public_id", "recorded_at", "weight", "unit", "weight_kg", "body_fat_percent",
        "muscle_mass_kg", "water_percent", "visceral_fat", "bmr_kcal", "bmi", "notes",
        "source", "client_event_id", "base_revision",
    }
    if set(payload) - allowed:
        raise MobileSyncError("invalid_request", "La medición contiene campos desconocidos.")
    values = {}
    if creating or "recorded_at" in payload:
        values["recorded_at"] = _timestamp(payload.get("recorded_at"))
    if "weight" in payload and "weight_kg" in payload:
        raise MobileSyncError("invalid_request", "Usa weight o weight_kg, no ambos.")
    if creating or "weight" in payload or "weight_kg" in payload:
        unit = payload.get("unit", "kg")
        if unit not in {"kg", "lb"}:
            raise MobileSyncError("invalid_request", "unit debe ser kg o lb.")
        weight = _decimal(payload.get("weight", payload.get("weight_kg")), field="weight", minimum="0.001", maximum=1000)
        if weight is None:
            raise MobileSyncError("invalid_request", "weight es obligatorio.")
        kilograms = weight * LB_TO_KG if unit == "lb" else weight
        values["weight_kg"] = kilograms.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    mappings = {
        "body_fat_percent": ("body_fat_percentage", 100),
        "muscle_mass_kg": ("muscle_mass_kg", 1000),
        "water_percent": ("water_percentage", 100),
        "visceral_fat": ("visceral_fat", 1000),
        "bmr_kcal": ("bmr_kcal", 100000),
        "bmi": ("bmi", 1000),
    }
    for external, (internal, maximum) in mappings.items():
        if external in payload:
            values[internal] = _decimal(payload[external], field=external, maximum=maximum)
    if "notes" in payload:
        values["notes"] = _text(payload["notes"], field="notes", maximum=2000)
    if creating:
        source = payload.get("source", "manual")
        if source not in BODY_SOURCES:
            raise MobileSyncError("invalid_request", "source no es válido para una medición corporal.")
        values["source"] = source
        if payload.get("client_event_id") is not None:
            values["client_event_id"] = _uuid(payload["client_event_id"], "client_event_id")
    elif "source" in payload:
        if payload["source"] != "user_override":
            raise MobileSyncError("invalid_request", "Solo se admite separar una copia editada.")
        values["source"] = "user_override"
    if not creating and payload.get("client_event_id") is not None:
        values["client_event_id"] = _uuid(payload["client_event_id"], "client_event_id")
    return values


def list_body_stats(user_id: int, *, limit: int, cursor: str | None) -> dict:
    if not 1 <= limit <= 100:
        raise MobileSyncError("invalid_limit", "El límite debe estar entre 1 y 100.")
    statement = db.select(WeighIn).where(WeighIn.user_id == user_id)
    if cursor:
        try:
            recorded_at, public_id = _serializer("mobile-body-stats-v1").loads(cursor)
            recorded_at = _timestamp(recorded_at)
            public_id = _uuid(public_id)
        except (BadData, TypeError, ValueError, MobileSyncError) as error:
            raise MobileSyncError("invalid_cursor", "El cursor no es válido.") from error
        statement = statement.where(
            db.or_(
                WeighIn.recorded_at < recorded_at,
                db.and_(WeighIn.recorded_at == recorded_at, WeighIn.public_id < public_id),
            )
        )
    rows = db.session.execute(
        statement.order_by(WeighIn.recorded_at.desc(), WeighIn.public_id.desc()).limit(limit + 1)
    ).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [serialize_body_stat(item) for item in rows],
        "next_cursor": _serializer("mobile-body-stats-v1").dumps(
            [rfc3339(rows[-1].recorded_at), rows[-1].public_id]
        ) if has_more and rows else None,
        "has_more": has_more,
    }


def create_body_stat(user_id: int, payload: dict) -> WeighIn:
    values = _body_values(payload, creating=True)
    client_event_id = values.get("client_event_id")
    if client_event_id:
        existing = db.session.execute(db.select(WeighIn).where(
            WeighIn.user_id == user_id, WeighIn.client_event_id == client_event_id
        )).scalar_one_or_none()
        if existing is not None:
            return existing
    public_id = _uuid(payload.get("public_id") or str(uuid.uuid4()))
    if db.session.execute(db.select(WeighIn.id).where(WeighIn.public_id == public_id)).scalar_one_or_none():
        raise MobileSyncError("conflict", "El ID ya existe.", 409)
    duplicate = db.session.execute(
        db.select(WeighIn.id).where(
            WeighIn.user_id == user_id,
            WeighIn.recorded_at == values["recorded_at"],
            WeighIn.source == values["source"],
        )
    ).scalar_one_or_none()
    if duplicate:
        raise MobileSyncError("duplicate", "Ya existe una medición en ese instante.", 409)
    record = WeighIn(public_id=public_id, user_id=user_id, **values)
    db.session.add(record)
    db.session.flush()
    return record


def _owned_body(user_id: int, public_id: str, *, lock=False) -> WeighIn:
    statement = db.select(WeighIn).where(
        WeighIn.user_id == user_id, WeighIn.public_id == _uuid(public_id)
    )
    if lock:
        statement = statement.with_for_update()
    record = db.session.execute(statement).scalar_one_or_none()
    if record is None:
        raise MobileSyncError("not_found", "Medición no encontrada.", 404)
    return record


def patch_body_stat(user_id: int, public_id: str, payload: dict) -> WeighIn:
    record = _owned_body(user_id, public_id, lock=True)
    _check_revision(record.revision, payload.get("base_revision"))
    values = _body_values(payload, creating=False)
    if "source" in values and not (record.source == "health_connect" and values["source"] == "user_override"):
        raise MobileSyncError("invalid_request", "La transición de procedencia no es válida.")
    if "client_event_id" in values and record.client_event_id not in {None, values["client_event_id"]}:
        raise MobileSyncError("conflict", "client_event_id pertenece a otra revisión.", 409)
    for field, value in values.items():
        setattr(record, field, value)
    record.revision += 1
    record.updated_at = datetime.now(timezone.utc)
    db.session.flush()
    return record


def delete_body_stat(user_id: int, public_id: str, payload: dict) -> dict:
    if set(payload) != {"base_revision"}:
        raise MobileSyncError("invalid_request", "Se requiere base_revision.")
    record = _owned_body(user_id, public_id, lock=True)
    _check_revision(record.revision, payload["base_revision"])
    revision = record.revision + 1
    db.session.delete(record)
    db.session.flush()
    return {"id": record.public_id, "deleted": True, "revision": revision}


def serialize_food(record: FoodProduct) -> dict:
    fields = {
        "serving_size_g": record.serving_size_g,
        "calories_per_100g": record.calories_per_100g,
        "protein_g_per_100g": record.protein_g_per_100g,
        "fat_g_per_100g": record.fat_g_per_100g,
        "carbs_g_per_100g": record.carbs_g_per_100g,
        "net_carbs_g_per_100g": record.net_carbs_g_per_100g,
        "fiber_g_per_100g": record.fiber_g_per_100g,
        "sodium_mg_per_100g": record.sodium_mg_per_100g,
    }
    return {
        "id": record.public_id,
        "name": record.name,
        "brand": record.brand,
        "serving_label": record.serving_label,
        **{key: _number(value) for key, value in fields.items()},
        "notes": record.notes,
        "custom": True,
        "archived": not record.is_active,
        "data_complete": all(
            value is not None
            for value in (
                record.calories_per_100g,
                record.protein_g_per_100g,
                record.fat_g_per_100g,
                record.carbs_g_per_100g,
            )
        ),
        "revision": record.revision,
        "updated_at": rfc3339(record.updated_at),
    }


def list_foods(user_id: int, *, search: str | None, limit: int, cursor: str | None, include_archived=False) -> dict:
    if not 1 <= limit <= 100:
        raise MobileSyncError("invalid_limit", "El límite debe estar entre 1 y 100.")
    query = _text(search, field="search", maximum=200) if search is not None else None
    statement = db.select(FoodProduct).where(FoodProduct.user_id == user_id)
    if not include_archived:
        statement = statement.where(FoodProduct.is_active.is_(True))
    if query:
        statement = statement.where(db.func.lower(FoodProduct.name).contains(query.casefold()))
    if cursor:
        try:
            name, public_id = _serializer("mobile-foods-v1").loads(cursor)
            public_id = _uuid(public_id)
        except (BadData, TypeError, ValueError, MobileSyncError) as error:
            raise MobileSyncError("invalid_cursor", "El cursor no es válido.") from error
        statement = statement.where(
            db.or_(
                db.func.lower(FoodProduct.name) > name,
                db.and_(db.func.lower(FoodProduct.name) == name, FoodProduct.public_id > public_id),
            )
        )
    rows = db.session.execute(
        statement.order_by(db.func.lower(FoodProduct.name), FoodProduct.public_id).limit(limit + 1)
    ).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [serialize_food(item) for item in rows],
        "next_cursor": _serializer("mobile-foods-v1").dumps(
            [rows[-1].name.casefold(), rows[-1].public_id]
        ) if has_more and rows else None,
        "has_more": has_more,
    }


def _food_values(payload: dict, *, creating: bool) -> dict:
    allowed = {
        "public_id", "name", "brand", "serving_size_g", "serving_label", "calories_per_100g",
        "protein_g_per_100g", "fat_g_per_100g", "carbs_g_per_100g", "net_carbs_g_per_100g",
        "fiber_g_per_100g", "sodium_mg_per_100g", "notes", "archived", "base_revision",
    }
    if set(payload) - allowed:
        raise MobileSyncError("invalid_request", "El alimento contiene campos desconocidos.")
    values = {}
    if creating or "name" in payload:
        values["name"] = _text(payload.get("name"), field="name", maximum=200, required=True)
    for field, maximum in (("brand", 200), ("serving_label", 64), ("notes", 2000)):
        if field in payload:
            values[field] = _text(payload[field], field=field, maximum=maximum)
    for field in (
        "serving_size_g", "calories_per_100g", "protein_g_per_100g", "fat_g_per_100g",
        "carbs_g_per_100g", "net_carbs_g_per_100g", "fiber_g_per_100g", "sodium_mg_per_100g",
    ):
        if field in payload:
            values[field] = _decimal(payload[field], field=field)
    if "archived" in payload:
        if not isinstance(payload["archived"], bool):
            raise MobileSyncError("invalid_request", "archived debe ser booleano.")
        values["is_active"] = not payload["archived"]
    return values


def create_food(user_id: int, payload: dict) -> FoodProduct:
    values = _food_values(payload, creating=True)
    public_id = _uuid(payload.get("public_id") or str(uuid.uuid4()))
    duplicate_id = db.session.execute(db.select(FoodProduct.id).where(FoodProduct.public_id == public_id)).scalar_one_or_none()
    if duplicate_id:
        raise MobileSyncError("conflict", "El ID ya existe.", 409)
    duplicate_name = db.session.execute(
        db.select(FoodProduct.id).where(
            FoodProduct.user_id == user_id,
            db.func.lower(FoodProduct.name) == values["name"].casefold(),
            FoodProduct.brand.is_(None) if values.get("brand") is None else db.func.lower(FoodProduct.brand) == values["brand"].casefold(),
        )
    ).scalar_one_or_none()
    if duplicate_name:
        raise MobileSyncError("duplicate", "Ya existe un alimento con ese nombre y marca.", 409)
    values.setdefault("is_active", True)
    record = FoodProduct(public_id=public_id, user_id=user_id, source="manual", **values)
    db.session.add(record)
    db.session.flush()
    return record


def patch_food(user_id: int, public_id: str, payload: dict) -> FoodProduct:
    record = db.session.execute(
        db.select(FoodProduct).where(
            FoodProduct.user_id == user_id, FoodProduct.public_id == _uuid(public_id)
        ).with_for_update()
    ).scalar_one_or_none()
    if record is None:
        raise MobileSyncError("not_found", "Alimento no encontrado.", 404)
    _check_revision(record.revision, payload.get("base_revision"))
    for field, value in _food_values(payload, creating=False).items():
        setattr(record, field, value)
    record.revision += 1
    record.updated_at = datetime.now(timezone.utc)
    db.session.flush()
    return record


def _owned_item(user_id: int, public_id: str, *, lock=False) -> NutritionItem:
    statement = (
        db.select(NutritionItem)
        .where(NutritionItem.user_id == user_id, NutritionItem.public_id == _uuid(public_id))
        .options(
            selectinload(NutritionItem.meal).selectinload(NutritionMeal.daily_nutrition),
            selectinload(NutritionItem.food_product),
        )
    )
    if lock:
        statement = statement.with_for_update()
    record = db.session.execute(statement).scalar_one_or_none()
    if record is None:
        raise MobileSyncError("not_found", "Entrada nutricional no encontrada.", 404)
    return record


def _nutrition_item_values(user_id: int, payload: dict, *, creating: bool) -> dict:
    allowed = {
        "public_id", "date", "meal_type", "meal_name", "name", "quantity", "unit", "food_id",
        "calories_kcal", "protein_g", "fat_g", "net_carbs_g", "total_carbs_g", "fiber_g",
        "sugar_g", "sodium_mg", "notes", "source", "client_event_id", "base_revision",
    }
    if set(payload) - allowed:
        raise MobileSyncError("invalid_request", "La entrada nutricional contiene campos desconocidos.")
    values = {}
    if creating or "name" in payload:
        values["name"] = _text(payload.get("name"), field="name", maximum=200, required=True)
    if creating or "date" in payload:
        values["date"] = _date(payload.get("date"))
    if creating or "meal_type" in payload:
        meal_type = payload.get("meal_type")
        if meal_type not in MEAL_TYPES:
            raise MobileSyncError("invalid_request", "meal_type no es válido.")
        values["meal_type"] = meal_type
    if "meal_name" in payload:
        values["meal_name"] = _text(payload["meal_name"], field="meal_name", maximum=200)
    if "quantity" in payload:
        values["quantity"] = _decimal(payload["quantity"], field="quantity")
    if "unit" in payload:
        values["unit"] = _text(payload["unit"], field="unit", maximum=32)
    if "notes" in payload:
        values["notes"] = _text(payload["notes"], field="notes", maximum=2000)
    external_metrics = {"calories_kcal": "calories", **{field: field for field in NUTRITION_FIELDS if field != "calories"}}
    for external, internal in external_metrics.items():
        if external in payload:
            values[internal] = _decimal(payload[external], field=external)
    if "food_id" in payload:
        if payload["food_id"] is None:
            values["food_product_id"] = None
        else:
            food = db.session.execute(
                db.select(FoodProduct).where(
                    FoodProduct.user_id == user_id,
                    FoodProduct.public_id == _uuid(payload["food_id"], "El ID de alimento"),
                    FoodProduct.is_active.is_(True),
                )
            ).scalar_one_or_none()
            if food is None:
                raise MobileSyncError("not_found", "Alimento no encontrado.", 404)
            values["food_product_id"] = food.id
    if creating:
        source = payload.get("source", "manual")
        if source not in NUTRITION_SOURCES:
            raise MobileSyncError("invalid_request", "source no es válido para nutrición.")
        values["source"] = source
        if payload.get("client_event_id") is not None:
            values["client_event_id"] = _uuid(payload["client_event_id"], "client_event_id")
    elif "source" in payload:
        if payload["source"] != "user_override":
            raise MobileSyncError("invalid_request", "Solo se admite separar una copia editada.")
        values["source"] = "user_override"
    if not creating and payload.get("client_event_id") is not None:
        values["client_event_id"] = _uuid(payload["client_event_id"], "client_event_id")
    return values


def _day(user_id: int, target: date, *, eager=True) -> DailyNutrition | None:
    statement = db.select(DailyNutrition).where(
        DailyNutrition.user_id == user_id, DailyNutrition.date == target
    )
    if eager:
        statement = statement.options(
            selectinload(DailyNutrition.meals)
            .selectinload(NutritionMeal.items)
            .selectinload(NutritionItem.food_product)
        )
    return db.session.execute(statement).scalar_one_or_none()


def _ensure_day(user_id: int, target: date) -> DailyNutrition:
    record = _day(user_id, target, eager=False)
    if record is None:
        record = DailyNutrition(user_id=user_id, date=target, source="manual")
        db.session.add(record)
        db.session.flush()
    return record


def _ensure_meal(day: DailyNutrition, meal_type: str, name: str | None = None) -> NutritionMeal:
    meal = db.session.execute(
        db.select(NutritionMeal).where(
            NutritionMeal.user_id == day.user_id,
            NutritionMeal.daily_nutrition_id == day.id,
            NutritionMeal.meal_type == meal_type,
        ).order_by(NutritionMeal.sort_order).limit(1)
    ).scalar_one_or_none()
    if meal is None:
        position = (db.session.execute(
            db.select(db.func.max(NutritionMeal.sort_order)).where(
                NutritionMeal.daily_nutrition_id == day.id
            )
        ).scalar_one() or 0) + 1
        meal = NutritionMeal(
            user_id=day.user_id,
            daily_nutrition_id=day.id,
            meal_type=meal_type,
            name=name,
            sort_order=position,
        )
        db.session.add(meal)
        db.session.flush()
    elif name is not None:
        meal.name = name
    return meal


def _recalculate_day(day: DailyNutrition) -> None:
    items = db.session.execute(
        db.select(NutritionItem).join(NutritionMeal).where(
            NutritionMeal.daily_nutrition_id == day.id,
            NutritionItem.user_id == day.user_id,
        )
    ).scalars().all()
    for field in NUTRITION_FIELDS:
        values = [getattr(item, field) for item in items if getattr(item, field) is not None]
        setattr(day, field, sum(values, Decimal("0")) if values else None)
    day.updated_at = datetime.now(timezone.utc)


def serialize_nutrition_item(record: NutritionItem) -> dict:
    day = record.meal.daily_nutrition
    return {
        "id": record.public_id,
        "date": day.date.isoformat(),
        "meal_type": record.meal.meal_type,
        "meal_name": record.meal.name,
        "name": record.name,
        "quantity": _number(record.quantity),
        "unit": record.unit,
        "food_id": record.food_product.public_id if record.food_product else None,
        "calories_kcal": _number(record.calories),
        "protein_g": _number(record.protein_g),
        "fat_g": _number(record.fat_g),
        "net_carbs_g": _number(record.net_carbs_g),
        "total_carbs_g": _number(record.total_carbs_g),
        "fiber_g": _number(record.fiber_g),
        "sugar_g": _number(record.sugar_g),
        "sodium_mg": _number(record.sodium_mg),
        "notes": record.notes,
        "source": record.source,
        "client_event_id": record.client_event_id,
        "data_complete": all(
            value is not None for value in (
                record.calories, record.protein_g, record.fat_g,
                record.total_carbs_g if record.total_carbs_g is not None else record.net_carbs_g,
            )
        ),
        "revision": record.revision,
        "created_at": rfc3339(record.created_at),
        "updated_at": rfc3339(record.updated_at),
    }


def serialize_nutrition_day(user_id: int, target: date) -> dict:
    day = _day(user_id, target)
    if day is None:
        return {
            "date": target.isoformat(), "totals": {field if field != "calories" else "calories_kcal": None for field in NUTRITION_FIELDS},
            "targets": None, "remaining": None, "meals": [], "updated_at": None,
        }
    totals = {
        field if field != "calories" else "calories_kcal": _number(getattr(day, field))
        for field in NUTRITION_FIELDS
    }
    return {
        "date": target.isoformat(),
        "totals": totals,
        "targets": None,
        "remaining": None,
        "meals": [
            {
                "meal_type": meal.meal_type,
                "name": meal.name,
                "items": [serialize_nutrition_item(item) for item in meal.items],
            }
            for meal in day.meals
        ],
        "updated_at": rfc3339(day.updated_at),
    }


def create_nutrition_item(user_id: int, payload: dict) -> NutritionItem:
    values = _nutrition_item_values(user_id, payload, creating=True)
    client_event_id = values.get("client_event_id")
    if client_event_id:
        existing = db.session.execute(db.select(NutritionItem).where(
            NutritionItem.user_id == user_id,
            NutritionItem.client_event_id == client_event_id,
        )).scalar_one_or_none()
        if existing is not None:
            return _owned_item(user_id, existing.public_id)
    public_id = _uuid(payload.get("public_id") or str(uuid.uuid4()))
    if db.session.execute(db.select(NutritionItem.id).where(NutritionItem.public_id == public_id)).scalar_one_or_none():
        raise MobileSyncError("conflict", "El ID ya existe.", 409)
    target = values.pop("date")
    meal_type = values.pop("meal_type")
    meal_name = values.pop("meal_name", None)
    day = _ensure_day(user_id, target)
    meal = _ensure_meal(day, meal_type, meal_name)
    position = (db.session.execute(
        db.select(db.func.max(NutritionItem.sort_order)).where(
            NutritionItem.nutrition_meal_id == meal.id
        )
    ).scalar_one() or 0) + 1
    item = NutritionItem(
        public_id=public_id,
        user_id=user_id,
        nutrition_meal_id=meal.id,
        sort_order=position,
        **values,
    )
    db.session.add(item)
    db.session.flush()
    _recalculate_day(day)
    db.session.flush()
    return _owned_item(user_id, public_id)


def patch_nutrition_item(user_id: int, public_id: str, payload: dict) -> NutritionItem:
    item = _owned_item(user_id, public_id, lock=True)
    _check_revision(item.revision, payload.get("base_revision"))
    values = _nutrition_item_values(user_id, payload, creating=False)
    if "source" in values and not (item.source == "health_connect" and values["source"] == "user_override"):
        raise MobileSyncError("invalid_request", "La transición de procedencia no es válida.")
    if "client_event_id" in values and item.client_event_id not in {None, values["client_event_id"]}:
        raise MobileSyncError("conflict", "client_event_id pertenece a otra revisión.", 409)
    old_meal = item.meal
    old_day = old_meal.daily_nutrition
    target_date = values.pop("date", old_day.date)
    meal_type = values.pop("meal_type", old_meal.meal_type)
    meal_name = values.pop("meal_name", None)
    if target_date != old_day.date or meal_type != old_meal.meal_type:
        target_day = _ensure_day(user_id, target_date)
        target_meal = _ensure_meal(target_day, meal_type, meal_name)
        position = (db.session.execute(
            db.select(db.func.max(NutritionItem.sort_order)).where(
                NutritionItem.nutrition_meal_id == target_meal.id
            )
        ).scalar_one() or 0) + 1
        item.meal = target_meal
        item.sort_order = position
    elif meal_name is not None:
        old_meal.name = meal_name
        target_day = old_day
    else:
        target_day = old_day
    for field, value in values.items():
        setattr(item, field, value)
    item.revision += 1
    item.updated_at = datetime.now(timezone.utc)
    db.session.flush()
    _recalculate_day(old_day)
    if target_day.id != old_day.id:
        _recalculate_day(target_day)
    db.session.flush()
    return _owned_item(user_id, public_id)


def duplicate_nutrition_item(user_id: int, public_id: str, payload: dict) -> NutritionItem:
    source = _owned_item(user_id, public_id)
    if set(payload) - {"public_id", "date", "meal_type"}:
        raise MobileSyncError("invalid_request", "La duplicación contiene campos desconocidos.")
    document = {
        "public_id": payload.get("public_id") or str(uuid.uuid4()),
        "date": payload.get("date", source.meal.daily_nutrition.date.isoformat()),
        "meal_type": payload.get("meal_type", source.meal.meal_type),
        "meal_name": source.meal.name,
        "name": source.name,
        "quantity": _number(source.quantity),
        "unit": source.unit,
        "food_id": source.food_product.public_id if source.food_product else None,
        "calories_kcal": _number(source.calories),
        "protein_g": _number(source.protein_g),
        "fat_g": _number(source.fat_g),
        "net_carbs_g": _number(source.net_carbs_g),
        "total_carbs_g": _number(source.total_carbs_g),
        "fiber_g": _number(source.fiber_g),
        "sugar_g": _number(source.sugar_g),
        "sodium_mg": _number(source.sodium_mg),
        "notes": source.notes,
    }
    return create_nutrition_item(user_id, document)


def delete_nutrition_item(user_id: int, public_id: str, payload: dict) -> dict:
    if set(payload) != {"base_revision"}:
        raise MobileSyncError("invalid_request", "Se requiere base_revision.")
    item = _owned_item(user_id, public_id, lock=True)
    _check_revision(item.revision, payload["base_revision"])
    meal = item.meal
    day = meal.daily_nutrition
    revision = item.revision + 1
    db.session.delete(item)
    db.session.flush()
    remaining = db.session.execute(
        db.select(db.func.count(NutritionItem.id)).where(NutritionItem.nutrition_meal_id == meal.id)
    ).scalar_one()
    if not remaining:
        db.session.delete(meal)
        db.session.flush()
    day_items = db.session.execute(
        db.select(db.func.count(NutritionItem.id)).join(NutritionMeal).where(
            NutritionMeal.daily_nutrition_id == day.id
        )
    ).scalar_one()
    if not day_items:
        db.session.delete(day)
    else:
        _recalculate_day(day)
    db.session.flush()
    return {"id": item.public_id, "deleted": True, "revision": revision}


def serialize_step(record: DailyEnergy) -> dict:
    return {
        "id": record.public_id,
        "date": record.date.isoformat(),
        "steps": record.steps,
        "source": record.source,
        "client_event_id": record.client_event_id,
        "goal": None,
        "revision": record.revision,
        "created_at": rfc3339(record.created_at),
        "updated_at": rfc3339(record.updated_at),
    }


def list_steps(user_id: int, *, start: date, end: date, limit: int) -> dict:
    if end < start or (end - start).days > 366:
        raise MobileSyncError("invalid_range", "El rango de pasos no es válido.")
    if not 1 <= limit <= 500:
        raise MobileSyncError("invalid_limit", "El límite debe estar entre 1 y 500.")
    rows = db.session.execute(
        db.select(DailyEnergy).where(
            DailyEnergy.user_id == user_id,
            DailyEnergy.date.between(start, end),
            DailyEnergy.steps.is_not(None),
        ).order_by(DailyEnergy.date.desc(), DailyEnergy.source, DailyEnergy.public_id).limit(limit)
    ).scalars().all()
    return {"items": [serialize_step(item) for item in rows], "from": start.isoformat(), "to": end.isoformat()}


def _owned_step(user_id: int, public_id: str, *, lock=False) -> DailyEnergy:
    statement = db.select(DailyEnergy).where(
        DailyEnergy.user_id == user_id,
        DailyEnergy.public_id == _uuid(public_id),
        DailyEnergy.steps.is_not(None),
    )
    if lock:
        statement = statement.with_for_update()
    record = db.session.execute(statement).scalar_one_or_none()
    if record is None:
        raise MobileSyncError("not_found", "Registro de pasos no encontrado.", 404)
    return record


def create_steps(user_id: int, payload: dict) -> DailyEnergy:
    if set(payload) - {"public_id", "date", "steps", "source", "client_event_id"}:
        raise MobileSyncError("invalid_request", "El registro de pasos contiene campos desconocidos.")
    target = _date(payload.get("date"))
    count = _integer(payload.get("steps"), field="steps", minimum=0, maximum=10_000_000)
    source = payload.get("source", "manual")
    if source not in STEP_SOURCES:
        raise MobileSyncError("invalid_request", "source no es válido para pasos.")
    client_event_id = payload.get("client_event_id")
    if client_event_id is not None:
        client_event_id = _uuid(client_event_id, "client_event_id")
        existing = db.session.execute(db.select(DailyEnergy).where(
            DailyEnergy.user_id == user_id,
            DailyEnergy.client_event_id == client_event_id,
        )).scalar_one_or_none()
        if existing is not None:
            return existing
    duplicate = db.session.execute(
        db.select(DailyEnergy).where(
            DailyEnergy.user_id == user_id, DailyEnergy.date == target, DailyEnergy.source == source
        )
    ).scalar_one_or_none()
    if duplicate:
        if duplicate.steps is None:
            duplicate.steps = count
            duplicate.revision += 1
            duplicate.updated_at = datetime.now(timezone.utc)
            db.session.flush()
            return duplicate
        raise MobileSyncError("duplicate", "Ya existe esa fuente para ese día.", 409)
    public_id = _uuid(payload.get("public_id") or str(uuid.uuid4()))
    if db.session.execute(db.select(DailyEnergy.id).where(DailyEnergy.public_id == public_id)).scalar_one_or_none():
        raise MobileSyncError("conflict", "El ID ya existe.", 409)
    record = DailyEnergy(
        public_id=public_id, user_id=user_id, date=target, steps=count,
        source=source, client_event_id=client_event_id,
    )
    db.session.add(record)
    db.session.flush()
    return record


def patch_steps(user_id: int, public_id: str, payload: dict) -> DailyEnergy:
    if set(payload) - {"base_revision", "date", "steps", "client_event_id"}:
        raise MobileSyncError("invalid_request", "La corrección contiene campos desconocidos.")
    record = _owned_step(user_id, public_id, lock=True)
    _check_revision(record.revision, payload.get("base_revision"))
    if payload.get("client_event_id") is not None:
        client_event_id = _uuid(payload["client_event_id"], "client_event_id")
        if record.client_event_id not in {None, client_event_id}:
            raise MobileSyncError("conflict", "client_event_id pertenece a otra revisión.", 409)
        record.client_event_id = client_event_id
    if "date" in payload:
        target = _date(payload["date"])
        duplicate = db.session.execute(
            db.select(DailyEnergy.id).where(
                DailyEnergy.user_id == user_id,
                DailyEnergy.date == target,
                DailyEnergy.source == record.source,
                DailyEnergy.id != record.id,
            )
        ).scalar_one_or_none()
        if duplicate:
            raise MobileSyncError("duplicate", "Ya existe esa fuente para el día seleccionado.", 409)
        record.date = target
    if "steps" in payload:
        record.steps = _integer(payload["steps"], field="steps", minimum=0, maximum=10_000_000)
    record.revision += 1
    record.updated_at = datetime.now(timezone.utc)
    db.session.flush()
    return record


def delete_steps(user_id: int, public_id: str, payload: dict) -> dict:
    if set(payload) != {"base_revision"}:
        raise MobileSyncError("invalid_request", "Se requiere base_revision.")
    record = _owned_step(user_id, public_id, lock=True)
    _check_revision(record.revision, payload["base_revision"])
    revision = record.revision + 1
    # Preserve unrelated energy values from imported or richer records.
    if any(value is not None for value in (record.total_calories, record.active_calories, record.resting_calories, record.distance_meters)):
        record.steps = None
        record.revision = revision
        record.updated_at = datetime.now(timezone.utc)
    else:
        db.session.delete(record)
    db.session.flush()
    return {"id": record.public_id, "deleted": True, "revision": revision}


def health_today(user_id: int, target: date, timezone_name: str | None) -> dict:
    zone = _timezone(timezone_name)
    start, end = _day_bounds(target, zone)
    weights = db.session.execute(
        db.select(WeighIn).where(
            WeighIn.user_id == user_id, WeighIn.recorded_at < end
        ).order_by(
            WeighIn.recorded_at.desc(),
            db.case((WeighIn.source == "manual", 0), else_=1),
            WeighIn.id.desc(),
        ).limit(2)
    ).scalars().all()
    nutrition = _day(user_id, target)
    energy = effective_energy_record(user_id, target)
    planned = db.session.execute(
        db.select(PlannedWorkout).where(
            PlannedWorkout.user_id == user_id,
            PlannedWorkout.scheduled_for_date == target,
            PlannedWorkout.deleted_at.is_(None),
        ).options(selectinload(PlannedWorkout.completed_session)).order_by(PlannedWorkout.id)
    ).scalars().all()
    latest_weight = weights[0] if weights else None
    exact_weight = latest_weight is not None and start <= (
        latest_weight.recorded_at.replace(tzinfo=timezone.utc) if latest_weight.recorded_at.tzinfo is None else latest_weight.recorded_at.astimezone(timezone.utc)
    ) < end
    updated_values = [
        value for value in (
            latest_weight.updated_at if latest_weight else None,
            nutrition.updated_at if nutrition else None,
            energy.updated_at if energy else None,
            *(item.updated_at for item in planned),
        ) if value is not None
    ]
    nutrition_totals = {
        "calories_kcal": _number(nutrition.calories) if nutrition else None,
        "protein_g": _number(nutrition.protein_g) if nutrition else None,
        "carbohydrate_g": _number(
            nutrition.total_carbs_g if nutrition and nutrition.total_carbs_g is not None else nutrition.net_carbs_g if nutrition else None
        ),
        "fat_g": _number(nutrition.fat_g) if nutrition else None,
        "fiber_g": _number(nutrition.fiber_g) if nutrition else None,
    }
    return {
        "date": target.isoformat(),
        "timezone": zone.key,
        "weight": serialize_body_stat(latest_weight) if latest_weight else None,
        "weight_is_exact_date": exact_weight,
        "nutrition": {"totals": nutrition_totals, "targets": None, "remaining": None},
        "steps": {
            "value": energy.steps if energy else None,
            "source": energy.source if energy else None,
            "goal": None,
            "entry_id": energy.public_id if energy and energy.steps is not None else None,
        },
        "training": {
            "scheduled": len(planned),
            "completed": sum(item.status == "completed" or item.completed_session is not None for item in planned),
            "items": [
                {"id": item.public_id, "title": item.title_snapshot, "status": item.status}
                for item in planned
            ],
        },
        "sync_status": "authoritative",
        "updated_at": rfc3339(max(updated_values)) if updated_values else None,
    }


def health_progress(user_id: int, start: date, end: date, timezone_name: str | None) -> dict:
    if end < start or (end - start).days > 366:
        raise MobileSyncError("invalid_range", "El rango de progreso no es válido.")
    zone = _timezone(timezone_name)
    start_at, _ = _day_bounds(start, zone)
    _, end_at = _day_bounds(end, zone)
    weights = db.session.execute(
        db.select(WeighIn).where(
            WeighIn.user_id == user_id,
            WeighIn.recorded_at >= start_at,
            WeighIn.recorded_at < end_at,
        ).order_by(
            WeighIn.recorded_at,
            db.case((WeighIn.source == "manual", 1), else_=0),
            WeighIn.id,
        )
    ).scalars().all()
    nutrition = db.session.execute(
        db.select(DailyNutrition).where(
            DailyNutrition.user_id == user_id, DailyNutrition.date.between(start, end)
        )
    ).scalars().all()
    energy = db.session.execute(
        db.select(DailyEnergy).where(
            DailyEnergy.user_id == user_id,
            DailyEnergy.date.between(start, end),
            DailyEnergy.steps.is_not(None),
        ).order_by(DailyEnergy.updated_at.desc(), DailyEnergy.id.desc())
    ).scalars().all()
    effective_steps = {}
    for record in energy:
        existing = effective_steps.get(record.date)
        if existing is None or record.source == "manual":
            effective_steps[record.date] = record
    weight_by_date = {}
    for record in weights:
        value = record.recorded_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        weight_by_date[value.astimezone(zone).date()] = record
    nutrition_by_date = {record.date: record for record in nutrition}
    points = []
    current = start
    while current <= end:
        weight = weight_by_date.get(current)
        day = nutrition_by_date.get(current)
        step = effective_steps.get(current)
        points.append({
            "date": current.isoformat(),
            "weight_kg": _number(weight.weight_kg) if weight else None,
            "steps": step.steps if step else None,
            "calories_kcal": _number(day.calories) if day else None,
            "protein_g": _number(day.protein_g) if day else None,
            "carbohydrate_g": _number(day.total_carbs_g if day and day.total_carbs_g is not None else day.net_carbs_g if day else None),
            "fat_g": _number(day.fat_g) if day else None,
            "weight_source": weight.source if weight else None,
            "steps_source": step.source if step else None,
        })
        current += timedelta(days=1)
    return {"from": start.isoformat(), "to": end.isoformat(), "timezone": zone.key, "points": points}
