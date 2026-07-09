"""Standard JSON generation for assisted daily nutrition candidates."""

from __future__ import annotations

from typing import Any

from app.services.importers.standard_generators.common import (
    coerce_number,
    drop_none,
)
from app.services.importers.standard_generators.weigh_in import normalize_source_type
from app.services.importers.universal_json_import_assistant import (
    DAILY_NUTRITION_ALIASES,
    _normalize_key,
)


SCHEMA_NAME = "daily_nutrition"

DATA_FIELDS = {
    "date",
    "source",
    "notes",
    "calories_kcal",
    "protein_g",
    "fat_g",
    "net_carbs_g",
    "total_carbs_g",
    "carbohydrate_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
}

NUMERIC_DATA_FIELDS = {
    "calories_kcal",
    "protein_g",
    "fat_g",
    "net_carbs_g",
    "total_carbs_g",
    "carbohydrate_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
}

ITEM_FIELDS = {
    "name",
    "quantity",
    "unit",
    "food_product_id",
    "recipe_id",
    "sort_order",
    "calories_kcal",
    "protein_g",
    "fat_g",
    "net_carbs_g",
    "total_carbs_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
    "notes",
}

NUMERIC_ITEM_FIELDS = NUMERIC_DATA_FIELDS | {"quantity"}
INTEGER_ITEM_FIELDS = {"food_product_id", "recipe_id", "sort_order"}

LOCAL_ALIASES = {
    "fecha": "date",
    "date": "date",
    "fuente": "source",
    "source": "source",
    "nota": "notes",
    "notas": "notes",
    "notes": "notes",
    "kcal": "calories_kcal",
    "calorias": "calories_kcal",
    "calories": "calories_kcal",
    "calories_kcal": "calories_kcal",
    "proteina": "protein_g",
    "proteina_g": "protein_g",
    "protein": "protein_g",
    "protein_g": "protein_g",
    "grasa": "fat_g",
    "grasa_g": "fat_g",
    "fat": "fat_g",
    "fat_g": "fat_g",
    "carbos_netos_g": "net_carbs_g",
    "net_carbs": "net_carbs_g",
    "net_carbs_g": "net_carbs_g",
    "carbohidratos": "total_carbs_g",
    "carbs": "total_carbs_g",
    "carbs_g": "total_carbs_g",
    "total_carbs_g": "total_carbs_g",
    "carbohydrate_g": "carbohydrate_g",
    "fibra": "fiber_g",
    "fibra_g": "fiber_g",
    "fiber": "fiber_g",
    "fiber_g": "fiber_g",
    "azucares": "sugar_g",
    "azucares_g": "sugar_g",
    "sugar": "sugar_g",
    "sugar_g": "sugar_g",
    "sugars_g": "sugar_g",
    "sodio": "sodium_mg",
    "sodio_mg": "sodium_mg",
    "sodium": "sodium_mg",
    "sodium_mg": "sodium_mg",
    "totales": "totals",
    "totals": "totals",
    "comidas": "meals",
    "meals": "meals",
    "items": "items",
    "alimentos": "items",
    "desayuno": "breakfast",
    "breakfast": "breakfast",
    "comida": "lunch",
    "lunch": "lunch",
    "cena": "dinner",
    "dinner": "dinner",
    "snack": "snack",
    "snacks": "snack",
    "extra": "extra",
    "extras": "extra",
    "otro": "other",
    "other": "other",
    "meal_type": "meal_type",
    "tipo_comida": "meal_type",
    "nombre": "name",
    "name": "name",
    "food": "name",
    "food_name": "name",
    "alimento": "name",
    "cantidad": "quantity",
    "quantity": "quantity",
    "unidad": "unit",
    "unit": "unit",
    "food_product_id": "food_product_id",
    "recipe_id": "recipe_id",
    "orden": "sort_order",
    "sort_order": "sort_order",
    "micronutrientes": "micronutrients",
    "micronutrients": "micronutrients",
}

MEAL_SECTION_TO_TYPE = {
    "breakfast": "breakfast",
    "lunch": "lunch",
    "dinner": "dinner",
    "snack": "snack",
    "snacks": "snack",
    "extra": "extra",
    "extras": "extra",
    "other": "other",
}

NESTED_DAILY_NUTRITION_SEGMENTS = (
    ".meals",
    ".comidas",
    ".desayuno",
    ".breakfast",
    ".comida",
    ".lunch",
    ".cena",
    ".dinner",
    ".snack",
    ".snacks",
    ".extra",
    ".extras",
    ".items",
    ".alimentos",
)

ROOT_DAILY_NUTRITION_SEGMENTS = {
    "meals",
    "comidas",
    "desayuno",
    "breakfast",
    "comida",
    "lunch",
    "cena",
    "dinner",
    "snack",
    "snacks",
    "extra",
    "extras",
    "items",
    "alimentos",
}


def parent_path(path: str) -> str | None:
    """Return the daily nutrition parent path for nested meal/item candidates."""

    if path in ROOT_DAILY_NUTRITION_SEGMENTS:
        return "$"

    for segment in NESTED_DAILY_NUTRITION_SEGMENTS:
        index = path.find(segment)
        if index > 0:
            return path[:index] or "$"

    return None


def generate(
    *,
    records: list[dict[str, Any]],
    mapping: dict[str, str],
    user_id: int,
    source_type: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate daily_nutrition documents from an assisted candidate mapping.

    The generated documents use schema field names only. Missing required
    fields are not invented; validation reports them as invalid preview output.
    """

    documents: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, record in enumerate(records):
        data: dict[str, Any] = {"source": "assisted_import"}
        meals: list[dict[str, Any]] = []

        for source_field, value in record.items():
            canonical = _get_canonical(source_field, mapping)

            if canonical in MEAL_SECTION_TO_TYPE:
                meal = _meal_from_section(
                    value,
                    forced_meal_type=MEAL_SECTION_TO_TYPE[canonical],
                    mapping=mapping,
                    warnings=warnings,
                    record_index=index,
                )
                if meal:
                    meals.append(meal)
                continue

            if canonical == "meals":
                meals.extend(
                    _meals_from_source(
                        value,
                        mapping=mapping,
                        warnings=warnings,
                        record_index=index,
                    )
                )
                continue

            if canonical == "items":
                meal = _meal_from_items(
                    value,
                    mapping=mapping,
                    warnings=warnings,
                    record_index=index,
                )
                if meal:
                    meals.append(meal)
                continue

            if canonical == "totals":
                _apply_totals(
                    data,
                    value,
                    mapping=mapping,
                    warnings=warnings,
                    record_index=index,
                )
                continue

            schema_field = _schema_data_field(canonical)
            if schema_field is None:
                if canonical is not None:
                    warnings.append(
                        f"record {index}: unsupported daily_nutrition field "
                        f"ignored: {canonical} (from source: {source_field})"
                    )
                else:
                    warnings.append(
                        f"record {index}: unknown daily_nutrition source field "
                        f"ignored: {source_field}"
                    )
                continue

            _apply_data_field(data, schema_field, value)

        if meals:
            data["meals"] = meals

        documents.append(
            {
                "schema_version": "1.0",
                "record_type": "daily_nutrition",
                "user_id": user_id,
                "source_type": normalize_source_type(source_type),
                "data": drop_none(data),
            }
        )

    return documents, warnings


def _get_canonical(key: str, mapping: dict[str, str]) -> str | None:
    if key in mapping:
        return _schema_alias(mapping[key])

    normalized = _normalize_key(key)
    if normalized in LOCAL_ALIASES:
        return LOCAL_ALIASES[normalized]

    alias = DAILY_NUTRITION_ALIASES.get(normalized)
    if alias is not None:
        return _schema_alias(alias)

    return None


def _schema_alias(canonical: str) -> str:
    return LOCAL_ALIASES.get(_normalize_key(canonical), canonical)


def _schema_data_field(canonical: str | None) -> str | None:
    if canonical in DATA_FIELDS:
        return canonical
    return None


def _apply_data_field(data: dict[str, Any], schema_field: str, value: Any) -> None:
    if schema_field in NUMERIC_DATA_FIELDS:
        data[schema_field] = coerce_number(value)
    else:
        data[schema_field] = value


def _apply_totals(
    data: dict[str, Any],
    value: Any,
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
) -> None:
    if not isinstance(value, dict):
        warnings.append(
            f"record {record_index}: daily_nutrition totals ignored because it is not an object"
        )
        return

    for source_field, field_value in value.items():
        canonical = _get_canonical(source_field, mapping)
        schema_field = _schema_data_field(canonical)
        if schema_field is None:
            warnings.append(
                f"record {record_index}: unsupported daily_nutrition totals field "
                f"ignored: {source_field}"
            )
            continue
        _apply_data_field(data, schema_field, field_value)


def _meals_from_source(
    value: Any,
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        warnings.append(
            f"record {record_index}: daily_nutrition meals ignored because it is not a list"
        )
        return []

    meals: list[dict[str, Any]] = []
    for meal_index, meal_value in enumerate(value):
        meal = _meal_from_object(
            meal_value,
            mapping=mapping,
            warnings=warnings,
            record_index=record_index,
            meal_index=meal_index,
        )
        if meal:
            meals.append(meal)
    return meals


def _meal_from_section(
    value: Any,
    *,
    forced_meal_type: str,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
) -> dict[str, Any] | None:
    if isinstance(value, dict):
        meal = _meal_from_object(
            value,
            mapping=mapping,
            warnings=warnings,
            record_index=record_index,
            meal_index=0,
        )
        meal["meal_type"] = forced_meal_type
        return meal

    meal = _meal_from_items(
        value,
        mapping=mapping,
        warnings=warnings,
        record_index=record_index,
    )
    if meal:
        meal["meal_type"] = forced_meal_type
    return meal


def _meal_from_items(
    value: Any,
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
) -> dict[str, Any] | None:
    items = _items_from_source(
        value,
        mapping=mapping,
        warnings=warnings,
        record_index=record_index,
        meal_index=0,
    )
    if not items and not isinstance(value, list):
        return None
    return {"items": items}


def _meal_from_object(
    value: Any,
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
    meal_index: int,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    meal: dict[str, Any] = {}
    items_source: Any = None

    for source_field, field_value in value.items():
        canonical = _get_canonical(source_field, mapping)

        if canonical == "meal_type":
            meal_type = _meal_type(field_value)
            if meal_type:
                meal["meal_type"] = meal_type
        elif canonical in MEAL_SECTION_TO_TYPE:
            meal["meal_type"] = MEAL_SECTION_TO_TYPE[canonical]
        elif canonical == "name":
            meal["name"] = str(field_value)
        elif canonical == "sort_order":
            meal["sort_order"] = _int_or_none(field_value)
        elif canonical == "items":
            items_source = field_value
        elif canonical is not None:
            warnings.append(
                f"record {record_index}, meal {meal_index}: unsupported "
                f"daily_nutrition meal field ignored: {canonical}"
            )

    if items_source is not None:
        meal["items"] = _items_from_source(
            items_source,
            mapping=mapping,
            warnings=warnings,
            record_index=record_index,
            meal_index=meal_index,
        )

    return drop_none(meal)


def _items_from_source(
    value: Any,
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
    meal_index: int,
) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [
            _item_from_object(
                value,
                mapping=mapping,
                warnings=warnings,
                record_index=record_index,
                meal_index=meal_index,
                item_index=0,
            )
        ]

    if not isinstance(value, list):
        warnings.append(
            f"record {record_index}, meal {meal_index}: daily_nutrition items "
            "ignored because it is not a list"
        )
        return []

    items: list[dict[str, Any]] = []
    for item_index, item_value in enumerate(value):
        if isinstance(item_value, dict):
            items.append(
                _item_from_object(
                    item_value,
                    mapping=mapping,
                    warnings=warnings,
                    record_index=record_index,
                    meal_index=meal_index,
                    item_index=item_index,
                )
            )
        elif isinstance(item_value, str) and item_value.strip():
            items.append({"name": item_value.strip()})
    return [drop_none(item) for item in items]


def _item_from_object(
    value: dict[str, Any],
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
    meal_index: int,
    item_index: int,
) -> dict[str, Any]:
    item: dict[str, Any] = {}

    for source_field, field_value in value.items():
        canonical = _get_canonical(source_field, mapping)
        if canonical not in ITEM_FIELDS:
            if canonical is not None:
                warnings.append(
                    f"record {record_index}, meal {meal_index}, item {item_index}: "
                    f"unsupported daily_nutrition item field ignored: {canonical}"
                )
            continue

        if canonical in INTEGER_ITEM_FIELDS:
            item[canonical] = _int_or_none(field_value)
        elif canonical in NUMERIC_ITEM_FIELDS:
            item[canonical] = coerce_number(field_value)
        else:
            item[canonical] = field_value

    return drop_none(item)


def _meal_type(value: Any) -> str | None:
    normalized = _normalize_key(str(value))
    canonical = LOCAL_ALIASES.get(normalized, normalized)
    return MEAL_SECTION_TO_TYPE.get(canonical)


def _int_or_none(value: Any) -> int | None:
    number = coerce_number(value)
    if number is None:
        return None
    return int(number)
