from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.extensions import db
from app.models import FoodProduct, Recipe, UploadedFile
from app.services.importers.base import ImporterError, load_json_source
from app.services.recipes import RecipeServiceError, create_recipe_from_products
from app.services.validation import validate_json_document


class RecipeBundleImportError(ValueError):
    pass


@dataclass
class RecipeBundleImportResult:
    created: list[Recipe]
    duplicates: list[Recipe]


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception as error:
        raise RecipeBundleImportError(f"{field_name} must be a valid number") from error
    if number <= 0:
        raise RecipeBundleImportError(f"{field_name} must be greater than zero")
    return number


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_product_by_id(user_id: int, product_id: int) -> FoodProduct:
    product = db.session.execute(
        db.select(FoodProduct).where(
            FoodProduct.id == product_id,
            FoodProduct.user_id == user_id,
        )
    ).scalar_one_or_none()

    if product is None:
        raise RecipeBundleImportError("Food product not found for this user")
    if not product.is_active:
        raise RecipeBundleImportError("Food product is inactive")
    return product


def _resolve_product_by_name(
    user_id: int,
    name: str,
    brand: str | None,
) -> FoodProduct:
    name = name.strip()
    brand = brand.strip() if brand else None

    query = db.select(FoodProduct).where(
        FoodProduct.user_id == user_id,
        FoodProduct.name == name,
        FoodProduct.is_active.is_(True),
    )
    if brand is None:
        query = query.where(FoodProduct.brand.is_(None))
    else:
        query = query.where(FoodProduct.brand == brand)

    products = db.session.execute(query).scalars().all()
    if not products:
        raise RecipeBundleImportError(f"Food product not found: {name}")
    if len(products) > 1:
        raise RecipeBundleImportError(f"Food product is ambiguous: {name}")
    return products[0]


def _ingredient_specs(recipe_document: dict[str, Any], user_id: int) -> list[dict[str, Any]]:
    specs = []
    seen_sort_orders: set[int] = set()

    for index, item in enumerate(recipe_document["ingredients"], start=1):
        if "food_product_id" in item:
            product = _resolve_product_by_id(user_id, int(item["food_product_id"]))
        else:
            product = _resolve_product_by_name(
                user_id,
                item["food_product_name"],
                item.get("food_product_brand"),
            )

        sort_order = int(item.get("sort_order", index))
        if sort_order in seen_sort_orders:
            raise RecipeBundleImportError("Recipe ingredient sort_order values must be unique")
        seen_sort_orders.add(sort_order)

        specs.append(
            {
                "food_product_id": product.id,
                "quantity_g": _decimal(item["quantity_g"], "quantity_g"),
                "sort_order": sort_order,
                "notes": _optional_text(item.get("notes")),
            }
        )

    return specs


def _existing_recipe(user_id: int, name: str) -> Recipe | None:
    return db.session.execute(
        db.select(Recipe).where(
            Recipe.user_id == user_id,
            Recipe.name == name,
        )
    ).scalar_one_or_none()


def import_recipe_bundle_file(
    source_file: UploadedFile,
    user_id: int,
) -> RecipeBundleImportResult:
    if source_file.user_id != user_id:
        raise RecipeBundleImportError("Recipe bundle file does not belong to this user")
    if source_file.source_type not in {"uploaded", "manual_generated"}:
        raise RecipeBundleImportError("Unsupported recipe bundle source file type")

    try:
        document = load_json_source(source_file, user_id)
    except ImporterError as error:
        raise RecipeBundleImportError(str(error)) from error

    validate_json_document(document, "recipe_bundle")

    document_user_id = document.get("user_id")
    if document_user_id is not None and document_user_id != user_id:
        raise RecipeBundleImportError("Recipe bundle document does not belong to this user")

    document_source_type = document.get("source_type", source_file.source_type)
    if document_source_type != source_file.source_type:
        raise RecipeBundleImportError("Recipe bundle source type does not match its file")

    created: list[Recipe] = []
    duplicates: list[Recipe] = []
    pending_creates: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []

    for recipe_document in document["recipes"]:
        validate_json_document(recipe_document, "recipe")

        recipe_user_id = recipe_document.get("user_id")
        if recipe_user_id is not None and recipe_user_id != user_id:
            raise RecipeBundleImportError("Recipe document does not belong to this user")

        recipe_source_type = recipe_document.get("source_type", document_source_type)
        if recipe_source_type != document_source_type:
            raise RecipeBundleImportError("Recipe source type does not match its bundle")

        recipe_name = recipe_document["name"].strip()
        existing = _existing_recipe(user_id, recipe_name)
        if existing is not None:
            duplicates.append(existing)
            continue

        pending_creates.append(
            (
                recipe_document,
                _ingredient_specs(recipe_document, user_id),
            )
        )

    try:
        for recipe_document, specs in pending_creates:
            created.append(
                create_recipe_from_products(
                    user_id=user_id,
                    name=recipe_document["name"],
                    description=_optional_text(recipe_document.get("description")),
                    servings=_decimal(recipe_document.get("servings", 1), "servings"),
                    yield_weight_g=(
                        _decimal(recipe_document["yield_weight_g"], "yield_weight_g")
                        if recipe_document.get("yield_weight_g") is not None
                        else None
                    ),
                    source=_optional_text(recipe_document.get("source")) or document_source_type,
                    notes=_optional_text(recipe_document.get("notes")),
                    ingredients=specs,
                    raw_payload_json=recipe_document,
                    commit=False,
                )
            )
        db.session.commit()
    except RecipeServiceError as error:
        db.session.rollback()
        raise RecipeBundleImportError(str(error)) from error

    return RecipeBundleImportResult(created=created, duplicates=duplicates)