from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import (
    DailyNutrition,
    NutritionItem,
    NutritionMeal,
    UploadedFile,
)
from app.services.importers.base import ImporterError, load_json_source
from app.services.validation import validate_json_document


class DailyNutritionImportError(ValueError):
    pass


FIELD_MAP = {
    "calories": "calories_kcal",
    "protein_g": "protein_g",
    "fat_g": "fat_g",
    "net_carbs_g": "net_carbs_g",
    "total_carbs_g": "total_carbs_g",
    "fiber_g": "fiber_g",
    "sugar_g": "sugar_g",
    "sodium_mg": "sodium_mg",
}


def _existing_record(source_file_id: int, user_id: int) -> DailyNutrition | None:
    return db.session.execute(
        db.select(DailyNutrition).where(
            DailyNutrition.source_file_id == source_file_id,
            DailyNutrition.user_id == user_id,
        )
    ).scalar_one_or_none()


def _decimal(value) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _totals(data: dict) -> dict[str, Decimal | None]:
    items = [
        item
        for meal in data.get("meals", [])
        for item in meal.get("items", [])
    ]
    totals = {}
    for model_field, document_field in FIELD_MAP.items():
        item_values = [
            _decimal(item[document_field])
            for item in items
            if item.get(document_field) is not None
        ]
        if item_values:
            totals[model_field] = sum(item_values, Decimal("0"))
            continue
        value = data.get(document_field)
        if model_field == "total_carbs_g" and value is None:
            value = data.get("carbohydrate_g")
        totals[model_field] = _decimal(value)
    return totals


def _validate_ordering(data: dict) -> None:
    meal_orders = [
        meal.get("sort_order", index)
        for index, meal in enumerate(data.get("meals", []), start=1)
    ]
    if len(meal_orders) != len(set(meal_orders)):
        raise DailyNutritionImportError("Meal sort_order values must be unique")
    for meal in data.get("meals", []):
        item_orders = [
            item.get("sort_order", index)
            for index, item in enumerate(meal["items"], start=1)
        ]
        if len(item_orders) != len(set(item_orders)):
            raise DailyNutritionImportError("Item sort_order values must be unique")
        if any(not item["name"].strip() for item in meal["items"]):
            raise DailyNutritionImportError("Nutrition item names must not be blank")


def import_daily_nutrition_file(
    source_file: UploadedFile,
    user_id: int,
) -> tuple[DailyNutrition, bool]:
    if source_file.user_id != user_id:
        raise DailyNutritionImportError(
            "Daily nutrition file does not belong to this user"
        )
    existing = _existing_record(source_file.id, user_id)
    if existing is not None:
        return existing, True
    if source_file.source_type not in {"uploaded", "manual_generated"}:
        raise DailyNutritionImportError("Unsupported daily nutrition source file type")

    try:
        document = load_json_source(source_file, user_id)
    except ImporterError as error:
        raise DailyNutritionImportError(str(error)) from error
    validate_json_document(document, "daily_nutrition")
    if document["user_id"] != user_id:
        raise DailyNutritionImportError(
            "Daily nutrition document does not belong to this user"
        )
    if document["source_type"] != source_file.source_type:
        raise DailyNutritionImportError(
            "Daily nutrition source type does not match its file"
        )

    data = document["data"]
    _validate_ordering(data)
    record_date = date.fromisoformat(data["date"])
    source = data.get("source", document["source_type"]).strip()
    if not source:
        raise DailyNutritionImportError("Daily nutrition source must not be blank")
    same_date = db.session.execute(
        db.select(DailyNutrition).where(
            DailyNutrition.user_id == user_id,
            DailyNutrition.date == record_date,
        )
    ).scalar_one_or_none()
    if same_date is not None:
        raise DailyNutritionImportError("Daily nutrition already exists for this date")

    record = DailyNutrition(
        user_id=user_id,
        date=record_date,
        source=source,
        source_file_id=source_file.id,
        notes=data.get("notes"),
        raw_payload_json=document,
        **_totals(data),
    )
    db.session.add(record)
    db.session.flush()

    for meal_index, meal_data in enumerate(data.get("meals", []), start=1):
        meal = NutritionMeal(
            user_id=user_id,
            daily_nutrition_id=record.id,
            meal_type=meal_data["meal_type"],
            name=meal_data.get("name"),
            sort_order=meal_data.get("sort_order", meal_index),
        )
        db.session.add(meal)
        db.session.flush()
        for item_index, item_data in enumerate(meal_data["items"], start=1):
            item_values = {
                model_field: _decimal(item_data.get(document_field))
                for model_field, document_field in FIELD_MAP.items()
            }
            db.session.add(
                NutritionItem(
                    user_id=user_id,
                    nutrition_meal_id=meal.id,
                    name=item_data["name"].strip(),
                    quantity=_decimal(item_data.get("quantity")),
                    unit=item_data.get("unit"),
                    food_product_id=item_data.get("food_product_id"),
                    sort_order=item_data.get("sort_order", item_index),
                    notes=item_data.get("notes"),
                    calories=item_values.pop("calories", None),
                    **item_values,
                )
            )
    db.session.commit()
    return record, False
