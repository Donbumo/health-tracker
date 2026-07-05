"""Tests for Recipe JSON importer."""

import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app.extensions import db
from app.models import FoodProduct, Recipe, UploadedFile, User
from app.services.importers.recipe import RecipeImportError, import_recipe_file
from app.services.validation import JsonSchemaValidationError


def _make_user(username: str) -> User:
    user = User(username=username, role="user")
    user.set_password("test-password")
    db.session.add(user)
    db.session.flush()
    return user


def _make_product(user_id: int, name: str = "Demo Product", **kwargs) -> FoodProduct:
    defaults = {
        "brand": "Demo Brand",
        "source": "manual",
        "calories_per_100g": Decimal("300.000"),
        "protein_g_per_100g": Decimal("20.000"),
        "fat_g_per_100g": Decimal("10.000"),
        "carbs_g_per_100g": Decimal("30.000"),
        "net_carbs_g_per_100g": Decimal("20.000"),
        "fiber_g_per_100g": Decimal("10.000"),
        "sodium_mg_per_100g": Decimal("100.000"),
    }
    defaults.update(kwargs)
    product = FoodProduct(user_id=user_id, name=name, **defaults)
    db.session.add(product)
    db.session.flush()
    return product


def _create_mock_source_file(
    app,
    user_id: int,
    document: dict,
    *,
    source_type: str = "uploaded",
) -> UploadedFile:
    filename = f"mock_recipe_{uuid.uuid4().hex}.json"
    upload_root = Path(app.config["UPLOAD_ROOT"])
    upload_root.mkdir(parents=True, exist_ok=True)
    storage_path = upload_root / filename
    storage_path.write_text(json.dumps(document), encoding="utf-8")

    file_record = UploadedFile(
        user_id=user_id,
        original_filename=filename,
        stored_filename=filename,
        storage_path=f"uploads/raw/{filename}",
        source_type=source_type,
        detected_type="recipe",
        size_bytes=storage_path.stat().st_size,
        mime_type="application/json",
        sha256=f"mockhash_{uuid.uuid4().hex}",
        import_status="pending",
    )
    db.session.add(file_record)
    db.session.commit()
    return file_record


def _document_by_name(product: FoodProduct, **overrides) -> dict:
    document = {
        "schema_version": "1.0",
        "type": "recipe",
        "name": "Imported Protein Shake",
        "description": "Imported recipe test.",
        "servings": 2,
        "yield_weight_g": 500,
        "source": "label_usuario",
        "notes": "Recipe notes.",
        "ingredients": [
            {
                "food_product_name": product.name,
                "food_product_brand": product.brand,
                "quantity_g": 40,
                "notes": "One serving.",
            }
        ],
    }
    document.update(overrides)
    return document


def _document_by_id(product: FoodProduct, **overrides) -> dict:
    document = {
        "schema_version": "1.0",
        "type": "recipe",
        "name": "Imported Recipe By ID",
        "servings": 1,
        "ingredients": [
            {
                "food_product_id": product.id,
                "quantity_g": 100,
            }
        ],
    }
    document.update(overrides)
    return document


def test_import_recipe_by_product_name_and_brand(app, user):
    with app.app_context():
        product = _make_product(
            user,
            "Proteína XGear / Dr. Simi aislado",
            brand="XGear / Dr. Simi",
            calories_per_100g=Decimal("380.000"),
            protein_g_per_100g=Decimal("85.000"),
            fat_g_per_100g=Decimal("2.000"),
            carbs_g_per_100g=Decimal("0.000"),
            net_carbs_g_per_100g=Decimal("0.000"),
            fiber_g_per_100g=Decimal("0.000"),
            sodium_mg_per_100g=Decimal("100.000"),
        )
        document = _document_by_name(product)
        source_file = _create_mock_source_file(app, user, document)

        recipe, duplicate = import_recipe_file(source_file, user)

        assert duplicate is False
        assert recipe.name == "Imported Protein Shake"
        assert recipe.source == "label_usuario"
        assert recipe.servings == Decimal("2.000")
        assert recipe.yield_weight_g == Decimal("500.000")
        assert len(recipe.ingredients) == 1

        ingredient = recipe.ingredients[0]
        assert ingredient.food_product_id == product.id
        assert ingredient.name_snapshot == "Proteína XGear / Dr. Simi aislado"
        assert ingredient.brand_snapshot == "XGear / Dr. Simi"
        assert ingredient.quantity_g == Decimal("40.000")
        assert ingredient.protein_g_per_100g == Decimal("85.000")

        totals = recipe.totals()
        assert totals["calories"] == Decimal("152.000000")
        assert totals["protein_g"] == Decimal("34.000000")
        assert totals["net_carbs_g"] == Decimal("0.000000")


def test_import_recipe_by_product_id(app, user):
    with app.app_context():
        product = _make_product(user, "ID Product", brand=None)
        document = _document_by_id(product)
        source_file = _create_mock_source_file(app, user, document)

        recipe, duplicate = import_recipe_file(source_file, user)

        assert duplicate is False
        assert recipe.name == "Imported Recipe By ID"
        assert recipe.ingredients[0].food_product_id == product.id
        assert recipe.ingredients[0].name_snapshot == "ID Product"


def test_import_duplicate_recipe_deduplicates_by_user_and_name(app, user):
    with app.app_context():
        product = _make_product(user, "Duplicate Import Product")
        document = _document_by_name(product, name="Duplicate Imported Recipe")

        source_file_1 = _create_mock_source_file(app, user, document)
        recipe_1, duplicate_1 = import_recipe_file(source_file_1, user)
        assert duplicate_1 is False

        source_file_2 = _create_mock_source_file(app, user, document)
        recipe_2, duplicate_2 = import_recipe_file(source_file_2, user)
        assert duplicate_2 is True
        assert recipe_1.id == recipe_2.id


def test_import_recipe_rejects_file_from_other_user(app, user):
    with app.app_context():
        second = _make_user("second-recipe-import-user")
        product = _make_product(second.id, "Other User Product")
        document = _document_by_name(product)
        source_file = _create_mock_source_file(app, second.id, document)

        with pytest.raises(RecipeImportError) as exc:
            import_recipe_file(source_file, user)

        assert "file does not belong to this user" in str(exc.value)


def test_import_recipe_rejects_document_user_mismatch(app, user):
    with app.app_context():
        second = _make_user("second-recipe-document-user")
        product = _make_product(user, "Own Product")
        document = _document_by_name(product, user_id=second.id)
        source_file = _create_mock_source_file(app, user, document)

        with pytest.raises(RecipeImportError) as exc:
            import_recipe_file(source_file, user)

        assert "document does not belong to this user" in str(exc.value)


def test_import_recipe_rejects_source_type_mismatch(app, user):
    with app.app_context():
        product = _make_product(user, "Source Type Product")
        document = _document_by_name(product, source_type="converted")
        source_file = _create_mock_source_file(app, user, document, source_type="uploaded")

        with pytest.raises(RecipeImportError) as exc:
            import_recipe_file(source_file, user)

        assert "source type does not match" in str(exc.value)


def test_import_recipe_rejects_missing_product(app, user):
    with app.app_context():
        document = {
            "schema_version": "1.0",
            "type": "recipe",
            "name": "Missing Product Recipe",
            "servings": 1,
            "ingredients": [
                {
                    "food_product_name": "No existe",
                    "food_product_brand": "Marca fantasma",
                    "quantity_g": 100,
                }
            ],
        }
        source_file = _create_mock_source_file(app, user, document)

        with pytest.raises(RecipeImportError) as exc:
            import_recipe_file(source_file, user)

        assert "Food product not found" in str(exc.value)


def test_import_recipe_rejects_inactive_product(app, user):
    with app.app_context():
        product = _make_product(user, "Inactive Recipe Product", is_active=False)
        document = _document_by_id(product)
        source_file = _create_mock_source_file(app, user, document)

        with pytest.raises(RecipeImportError) as exc:
            import_recipe_file(source_file, user)

        assert "inactive" in str(exc.value)


def test_import_recipe_invalid_schema(app, user):
    with app.app_context():
        document = {
            "schema_version": "1.0",
            "type": "recipe",
            "name": "Invalid Recipe"
        }
        source_file = _create_mock_source_file(app, user, document)

        with pytest.raises(JsonSchemaValidationError):
            import_recipe_file(source_file, user)