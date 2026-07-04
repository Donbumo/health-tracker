from decimal import Decimal
from typing import Any

from app.extensions import db
from app.models import FoodProduct, UploadedFile
from app.services.importers.base import ImporterError, load_json_source
from app.services.validation import validate_json_document


class FoodProductImportError(ValueError):
    pass


PRODUCT_FIELDS = (
    "name",
    "brand",
    "serving_size_g",
    "serving_label",
    "calories_per_100g",
    "protein_g_per_100g",
    "fat_g_per_100g",
    "carbs_g_per_100g",
    "net_carbs_g_per_100g",
    "fiber_g_per_100g",
    "sodium_mg_per_100g",
    "source",
    "notes",
)


def _decimal(value) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _product_data(document: dict[str, Any]) -> dict[str, Any]:
    """Return product payload from wrapped or flat food product JSON."""
    wrapped_data = document.get("data")
    if wrapped_data is not None:
        if not isinstance(wrapped_data, dict):
            raise FoodProductImportError("Food product data must be an object")
        return wrapped_data

    return {field: document[field] for field in PRODUCT_FIELDS if field in document}


def import_food_product_file(
    source_file: UploadedFile,
    user_id: int,
) -> tuple[FoodProduct, bool]:
    """Import a FoodProduct from a validated JSON source file.

    Accepts both:
    - flat user-facing food_product JSON.
    - legacy wrapped JSON with user_id/source_type/data.

    Deduplicates by (user_id, name, brand).
    """
    if source_file.user_id != user_id:
        raise FoodProductImportError("Food product file does not belong to this user")
    if source_file.source_type not in {"uploaded", "manual_generated"}:
        raise FoodProductImportError("Unsupported food product source file type")

    try:
        document = load_json_source(source_file, user_id)
    except ImporterError as error:
        raise FoodProductImportError(str(error)) from error

    validate_json_document(document, "food_product")

    document_user_id = document.get("user_id")
    if document_user_id is not None and document_user_id != user_id:
        raise FoodProductImportError(
            "Food product document does not belong to this user"
        )

    document_source_type = document.get("source_type", source_file.source_type)
    if document_source_type != source_file.source_type:
        raise FoodProductImportError(
            "Food product source type does not match its file"
        )

    data = _product_data(document)
    name = data["name"].strip()
    brand = data.get("brand")
    brand = brand.strip() if brand else None

    existing = db.session.execute(
        db.select(FoodProduct).where(
            FoodProduct.user_id == user_id,
            FoodProduct.name == name,
            FoodProduct.brand.is_(brand)
            if brand is None
            else FoodProduct.brand == brand,
        )
    ).scalar_one_or_none()

    if existing is not None:
        return existing, True

    source = data.get("source", document_source_type).strip()
    if not source:
        raise FoodProductImportError("Food product source must not be blank")

    product = FoodProduct(
        user_id=user_id,
        name=name,
        brand=brand,
        serving_size_g=_decimal(data.get("serving_size_g")),
        serving_label=data.get("serving_label"),
        calories_per_100g=_decimal(data.get("calories_per_100g")),
        protein_g_per_100g=_decimal(data.get("protein_g_per_100g")),
        fat_g_per_100g=_decimal(data.get("fat_g_per_100g")),
        carbs_g_per_100g=_decimal(data.get("carbs_g_per_100g")),
        net_carbs_g_per_100g=_decimal(data.get("net_carbs_g_per_100g")),
        fiber_g_per_100g=_decimal(data.get("fiber_g_per_100g")),
        sodium_mg_per_100g=_decimal(data.get("sodium_mg_per_100g")),
        source=source,
        notes=data.get("notes"),
        raw_payload_json=document,
    )
    db.session.add(product)
    db.session.commit()
    return product, False