"""Standard JSON generation for assisted recipe candidates."""

from __future__ import annotations

from typing import Any

from app.services.importers.standard_generators.common import (
    coerce_number,
    drop_none,
)
from app.services.importers.universal_json_import_assistant import (
    RECIPE_ALIASES,
    _normalize_key,
)


SCHEMA_NAME = "recipe"

ALLOWED_SOURCE_TYPES = {
    "uploaded",
    "manual_generated",
    "converted",
    "system_generated",
    "synced_from_device",
}

RECIPE_FIELDS = {
    "name",
    "description",
    "servings",
    "yield_weight_g",
    "source",
    "notes",
}

NUMERIC_RECIPE_FIELDS = {"servings", "yield_weight_g"}

INGREDIENT_FIELDS = {
    "food_product_id",
    "food_product_name",
    "food_product_brand",
    "quantity_g",
    "sort_order",
    "notes",
}

INTEGER_INGREDIENT_FIELDS = {"food_product_id", "sort_order"}
NUMERIC_INGREDIENT_FIELDS = {"quantity_g"}

LOCAL_ALIASES = {
    "receta": "name",
    "recipe": "name",
    "nombre": "name",
    "name": "name",
    "descripcion": "description",
    "description": "description",
    "notas": "notes",
    "notes": "notes",
    "fuente": "source",
    "source": "source",
    "porciones": "servings",
    "servings": "servings",
    "rendimiento": "yield_weight_g",
    "peso_final": "yield_weight_g",
    "yield_weight_g": "yield_weight_g",
    "ingredientes": "ingredients",
    "ingredients": "ingredients",
    "producto_id": "food_product_id",
    "food_product_id": "food_product_id",
    "alimento_id": "food_product_id",
    "producto": "food_product_name",
    "producto_nombre": "food_product_name",
    "food_product_name": "food_product_name",
    "alimento": "food_product_name",
    "ingrediente": "food_product_name",
    "marca": "food_product_brand",
    "brand": "food_product_brand",
    "food_product_brand": "food_product_brand",
    "cantidad_g": "quantity_g",
    "quantity_g": "quantity_g",
    "gramos": "quantity_g",
    "orden": "sort_order",
    "sort_order": "sort_order",
}

INGREDIENT_SEGMENTS = (".ingredients", ".ingredientes")
ROOT_INGREDIENT_SEGMENTS = {"ingredients", "ingredientes"}


def normalize_source_type(source_type: str) -> str:
    normalized = _normalize_key(source_type)
    if normalized in ALLOWED_SOURCE_TYPES:
        return normalized
    return "uploaded"


def parent_path(path: str) -> str | None:
    """Return the recipe object path for nested ingredient candidates."""

    if path in ROOT_INGREDIENT_SEGMENTS:
        return "$"

    for segment in INGREDIENT_SEGMENTS:
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
    documents: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, record in enumerate(records):
        documents.append(
            build_recipe_document(
                record,
                mapping=mapping,
                user_id=user_id,
                source_type=source_type,
                warnings=warnings,
                record_index=index,
            )
        )

    return documents, warnings


def build_recipe_document(
    record: dict[str, Any],
    *,
    mapping: dict[str, str],
    user_id: int,
    source_type: str,
    warnings: list[str],
    record_index: int,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "type": "recipe",
        "user_id": user_id,
        "source_type": normalize_source_type(source_type),
    }
    ingredients_source: Any = None

    for source_field, value in record.items():
        canonical = get_canonical(source_field, mapping)
        if canonical == "ingredients":
            ingredients_source = value
            continue

        if canonical in RECIPE_FIELDS:
            _apply_recipe_field(document, canonical, value)
            continue

        if canonical is not None:
            warnings.append(
                f"record {record_index}: unsupported recipe field ignored: "
                f"{canonical} (from source: {source_field})"
            )
        else:
            warnings.append(
                f"record {record_index}: unknown recipe source field ignored: "
                f"{source_field}"
            )

    if ingredients_source is not None:
        document["ingredients"] = _ingredients_from_source(
            ingredients_source,
            mapping=mapping,
            warnings=warnings,
            record_index=record_index,
        )

    return drop_none(document)


def get_canonical(key: str, mapping: dict[str, str]) -> str | None:
    if key in mapping:
        return _schema_alias(mapping[key])

    normalized = _normalize_key(key)
    if normalized in LOCAL_ALIASES:
        return LOCAL_ALIASES[normalized]

    alias = RECIPE_ALIASES.get(normalized)
    if alias is not None:
        return _schema_alias(alias)

    return None


def _schema_alias(canonical: str) -> str:
    return LOCAL_ALIASES.get(_normalize_key(canonical), canonical)


def _apply_recipe_field(document: dict[str, Any], canonical: str, value: Any) -> None:
    if canonical in NUMERIC_RECIPE_FIELDS:
        document[canonical] = coerce_number(value)
    else:
        document[canonical] = value


def _ingredients_from_source(
    value: Any,
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [
            _ingredient_from_object(
                value,
                mapping=mapping,
                warnings=warnings,
                record_index=record_index,
                ingredient_index=0,
            )
        ]

    if not isinstance(value, list):
        warnings.append(
            f"record {record_index}: recipe ingredients ignored because it is not a list"
        )
        return []

    ingredients: list[dict[str, Any]] = []
    for ingredient_index, item in enumerate(value):
        if isinstance(item, dict):
            ingredients.append(
                _ingredient_from_object(
                    item,
                    mapping=mapping,
                    warnings=warnings,
                    record_index=record_index,
                    ingredient_index=ingredient_index,
                )
            )
        elif isinstance(item, str) and item.strip():
            ingredients.append({"food_product_name": item.strip()})

    return [drop_none(item) for item in ingredients]


def _ingredient_from_object(
    value: dict[str, Any],
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
    ingredient_index: int,
) -> dict[str, Any]:
    ingredient: dict[str, Any] = {}

    for source_field, field_value in value.items():
        canonical = _ingredient_canonical(source_field, mapping)
        if canonical not in INGREDIENT_FIELDS:
            if canonical is not None:
                warnings.append(
                    f"record {record_index}, ingredient {ingredient_index}: "
                    f"unsupported recipe ingredient field ignored: {canonical}"
                )
            continue

        if canonical in INTEGER_INGREDIENT_FIELDS:
            ingredient[canonical] = _int_or_none(field_value)
        elif canonical in NUMERIC_INGREDIENT_FIELDS:
            ingredient[canonical] = coerce_number(field_value)
        else:
            ingredient[canonical] = field_value

    return drop_none(ingredient)


def _ingredient_canonical(key: str, mapping: dict[str, str]) -> str | None:
    canonical = get_canonical(key, mapping)
    if canonical == "name":
        return "food_product_name"
    return canonical


def _int_or_none(value: Any) -> int | None:
    number = coerce_number(value)
    if number is None:
        return None
    return int(number)
