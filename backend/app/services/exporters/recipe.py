"""Recipe JSON export helpers."""

import json
from decimal import Decimal
from typing import Any

from app.models import Recipe, RecipeIngredient
from app.services.validation import validate_json_document


def _number(value: Decimal | int | float | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _ingredient_document(ingredient: RecipeIngredient) -> dict[str, Any]:
    data: dict[str, Any] = {
        "food_product_name": ingredient.name_snapshot,
        "quantity_g": _number(ingredient.quantity_g),
        "sort_order": ingredient.sort_order,
    }

    if ingredient.brand_snapshot is not None:
        data["food_product_brand"] = ingredient.brand_snapshot

    notes = _optional_text(ingredient.notes)
    if notes:
        data["notes"] = notes

    return data


def build_recipe_export_document(recipe: Recipe) -> dict[str, Any]:
    """Build a portable recipe JSON document.

    Ingredients are exported by product name/brand snapshots instead of local
    database IDs so the file can be reimported in another environment if the
    matching pantry products exist.
    """
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "type": "recipe",
        "name": recipe.name,
        "servings": _number(recipe.servings),
        "source": recipe.source or "manual",
        "ingredients": [
            _ingredient_document(ingredient)
            for ingredient in sorted(recipe.ingredients, key=lambda item: item.sort_order)
        ],
    }

    description = _optional_text(recipe.description)
    if description:
        document["description"] = description

    if recipe.yield_weight_g is not None:
        document["yield_weight_g"] = _number(recipe.yield_weight_g)

    notes = _optional_text(recipe.notes)
    if notes:
        document["notes"] = notes

    validate_json_document(document, "recipe")
    return document


def recipe_export_bytes(recipe: Recipe) -> bytes:
    document = build_recipe_export_document(recipe)
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")