"""Standard JSON generation for assisted recipe bundle candidates."""

from __future__ import annotations

from typing import Any

from app.services.importers.standard_generators.common import drop_none
from app.services.importers.standard_generators import recipe


SCHEMA_NAME = "recipe_bundle"

LOCAL_ALIASES = {
    "nombre": "name",
    "name": "name",
    "recetas": "recipes",
    "recipes": "recipes",
}

RECIPE_COLLECTION_SEGMENTS = (".recipes", ".recetas")
ROOT_RECIPE_COLLECTION_SEGMENTS = {"recipes", "recetas"}


def parent_path(path: str) -> str | None:
    """Return the bundle object path for nested recipe candidates."""

    if path in ROOT_RECIPE_COLLECTION_SEGMENTS:
        return None

    for segment in RECIPE_COLLECTION_SEGMENTS:
        index = path.find(segment)
        if index > 0:
            return path[:index] or "$"

    return recipe.parent_path(path)


def generate(
    *,
    records: list[dict[str, Any]],
    mapping: dict[str, str],
    user_id: int,
    source_type: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate one recipe_bundle document from a bundle or recipe list.

    Missing required recipe fields are not invented. They are left absent so
    schema validation can mark the generated bundle invalid.
    """

    warnings: list[str] = []
    bundle: dict[str, Any] = {
        "schema_version": "1.0",
        "type": "recipe_bundle",
        "user_id": user_id,
        "source_type": recipe.normalize_source_type(source_type),
    }

    recipes_source: Any = records

    if len(records) == 1:
        record = records[0]
        for source_field, value in record.items():
            canonical = _get_canonical(source_field, mapping)
            if canonical == "name":
                bundle["name"] = value
            elif canonical == "recipes":
                recipes_source = value

    bundle["recipes"] = _recipes_from_source(
        recipes_source,
        mapping=mapping,
        user_id=user_id,
        source_type=source_type,
        warnings=warnings,
    )

    return [drop_none(bundle)], warnings


def _get_canonical(key: str, mapping: dict[str, str]) -> str | None:
    if key in mapping:
        return _schema_alias(mapping[key])

    normalized = recipe._normalize_key(key)
    if normalized in LOCAL_ALIASES:
        return LOCAL_ALIASES[normalized]

    return recipe.get_canonical(key, mapping)


def _schema_alias(canonical: str) -> str:
    return LOCAL_ALIASES.get(recipe._normalize_key(canonical), canonical)


def _recipes_from_source(
    value: Any,
    *,
    mapping: dict[str, str],
    user_id: int,
    source_type: str,
    warnings: list[str],
) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        recipe_records = [value]
    elif isinstance(value, list):
        recipe_records = [item for item in value if isinstance(item, dict)]
    else:
        warnings.append("recipe_bundle recipes ignored because it is not a list")
        recipe_records = []

    embedded: list[dict[str, Any]] = []
    for index, record in enumerate(recipe_records):
        embedded.append(
            recipe.build_recipe_document(
                record,
                mapping=mapping,
                user_id=user_id,
                source_type=source_type,
                warnings=warnings,
                record_index=index,
            )
        )

    return embedded
