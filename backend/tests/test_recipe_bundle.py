"""Tests for recipe bundle import/export."""

import json
import uuid
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from app.extensions import db
from app.models import FoodProduct, Recipe, UploadedFile, User
from app.services.exporters.recipe import (
    build_recipe_bundle_export_document,
    recipe_bundle_export_bytes,
)
from app.services.importers.recipe_bundle import import_recipe_bundle_file
from app.services.recipes import create_recipe_from_products
from app.services.validation import validate_json_document
from tests.conftest import login


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


def _make_recipe(
    user_id: int,
    product: FoodProduct,
    name: str = "Bundle Recipe",
    quantity_g: Decimal = Decimal("100.000"),
) -> Recipe:
    return create_recipe_from_products(
        user_id=user_id,
        name=name,
        description=f"{name} description",
        servings=Decimal("2.000"),
        yield_weight_g=Decimal("500.000"),
        notes=f"{name} notes",
        ingredients=[
            {
                "food_product_id": product.id,
                "quantity_g": quantity_g,
                "notes": f"{name} ingredient notes",
            }
        ],
    )


def _create_mock_source_file(
    app,
    user_id: int,
    document: dict,
    *,
    source_type: str = "uploaded",
) -> UploadedFile:
    filename = f"mock_recipe_bundle_{uuid.uuid4().hex}.json"
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
        detected_type="recipe_bundle",
        size_bytes=storage_path.stat().st_size,
        mime_type="application/json",
        sha256=f"mockhash_{uuid.uuid4().hex}",
        import_status="pending",
    )
    db.session.add(file_record)
    db.session.commit()
    return file_record


def _bundle_document_from_product(product: FoodProduct, *, names: list[str]) -> dict:
    return {
        "schema_version": "1.0",
        "type": "recipe_bundle",
        "name": "Test bundle",
        "recipes": [
            {
                "schema_version": "1.0",
                "type": "recipe",
                "name": recipe_name,
                "description": f"{recipe_name} description",
                "servings": 2,
                "yield_weight_g": 500,
                "source": "manual",
                "notes": f"{recipe_name} notes",
                "ingredients": [
                    {
                        "food_product_name": product.name,
                        "food_product_brand": product.brand,
                        "quantity_g": 100,
                        "sort_order": 1,
                        "notes": f"{recipe_name} ingredient notes",
                    }
                ],
            }
            for recipe_name in names
        ],
    }


def _json_upload(document: dict, filename: str = "recipes_bundle.json") -> tuple[BytesIO, str]:
    return BytesIO(json.dumps(document).encode("utf-8")), filename


def test_recipe_bundle_export_document_is_valid(app, user):
    with app.app_context():
        product = _make_product(user, "Bundle Product", brand="Bundle Brand")
        _make_recipe(user, product, name="Z Recipe")
        _make_recipe(user, product, name="A Recipe")
        db.session.commit()

        recipes = db.session.execute(
            db.select(Recipe).where(Recipe.user_id == user)
        ).scalars().all()

        document = build_recipe_bundle_export_document(recipes, name="My bundle")

        validate_json_document(document, "recipe_bundle")
        assert document["schema_version"] == "1.0"
        assert document["type"] == "recipe_bundle"
        assert document["name"] == "My bundle"
        assert [recipe["name"] for recipe in document["recipes"]] == [
            "A Recipe",
            "Z Recipe",
        ]
        assert document["recipes"][0]["ingredients"][0]["food_product_name"] == "Bundle Product"
        assert "food_product_id" not in document["recipes"][0]["ingredients"][0]


def test_recipe_bundle_export_bytes_are_pretty_json(app, user):
    with app.app_context():
        product = _make_product(user, "Pretty Bundle Product")
        recipe = _make_recipe(user, product, name="Pretty Bundle Recipe")
        db.session.commit()

        payload = recipe_bundle_export_bytes([recipe])
        text = payload.decode("utf-8")
        document = json.loads(text)

        assert text.endswith("\n")
        assert '\n  "recipes": [' in text
        assert document["type"] == "recipe_bundle"
        assert document["recipes"][0]["name"] == "Pretty Bundle Recipe"
        validate_json_document(document, "recipe_bundle")


def test_recipe_export_all_route_requires_login(client):
    response = client.get("/recipes/export-all")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_recipe_export_all_route_downloads_bundle(app, client, user):
    login(client)

    with app.app_context():
        product = _make_product(user, "Download Bundle Product", brand="Download Bundle Brand")
        _make_recipe(user, product, name="Bundle Download A")
        _make_recipe(user, product, name="Bundle Download B")
        db.session.commit()

    response = client.get("/recipes/export-all")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert response.headers["Content-Disposition"] == 'attachment; filename="recipes_bundle.json"'

    document = json.loads(response.data.decode("utf-8"))
    validate_json_document(document, "recipe_bundle")
    assert document["type"] == "recipe_bundle"
    assert len(document["recipes"]) == 2
    assert document["recipes"][0]["ingredients"][0]["food_product_name"] == "Download Bundle Product"


def test_recipe_import_bundle_file_creates_multiple_recipes(app, user):
    with app.app_context():
        product = _make_product(user, "Import Bundle Product", brand="Import Bundle Brand")
        document = _bundle_document_from_product(
            product,
            names=["Imported Bundle A", "Imported Bundle B"],
        )
        source_file = _create_mock_source_file(app, user, document)

        result = import_recipe_bundle_file(source_file, user)

        assert len(result.created) == 2
        assert len(result.duplicates) == 0
        assert {recipe.name for recipe in result.created} == {
            "Imported Bundle A",
            "Imported Bundle B",
        }

        saved = db.session.execute(
            db.select(Recipe).where(Recipe.user_id == user)
        ).scalars().all()
        assert len(saved) == 2
        assert saved[0].ingredients[0].name_snapshot == "Import Bundle Product"


def test_recipe_import_bundle_file_skips_duplicates(app, user):
    with app.app_context():
        product = _make_product(user, "Duplicate Bundle Product", brand="Duplicate Bundle Brand")
        _make_recipe(user, product, name="Existing Bundle Recipe")
        db.session.commit()

        document = _bundle_document_from_product(
            product,
            names=["Existing Bundle Recipe", "New Bundle Recipe"],
        )
        source_file = _create_mock_source_file(app, user, document)

        result = import_recipe_bundle_file(source_file, user)

        assert len(result.created) == 1
        assert len(result.duplicates) == 1
        assert result.created[0].name == "New Bundle Recipe"
        assert result.duplicates[0].name == "Existing Bundle Recipe"

        saved_names = {
            recipe.name
            for recipe in db.session.execute(
                db.select(Recipe).where(Recipe.user_id == user)
            ).scalars()
        }
        assert saved_names == {"Existing Bundle Recipe", "New Bundle Recipe"}


def test_recipe_import_bundle_web_upload(client, app, user):
    login(client)

    with app.app_context():
        product = _make_product(user, "Web Bundle Product", brand="Web Bundle Brand")
        db.session.commit()
        document = _bundle_document_from_product(
            product,
            names=["Web Bundle Recipe"],
        )

    response = client.post(
        "/recipes/import-bundle",
        data={"file": _json_upload(document)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Bundle de recetas importado" in response.data

    with app.app_context():
        recipe = db.session.execute(
            db.select(Recipe).where(
                Recipe.user_id == user,
                Recipe.name == "Web Bundle Recipe",
            )
        ).scalar_one()
        assert recipe.ingredients[0].name_snapshot == "Web Bundle Product"


def test_recipe_import_bundle_page_renders(client, app, user):
    login(client)

    response = client.get("/recipes/import-bundle")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Importar bundle de recetas" in body
    assert "Formato recomendado" in body


def test_recipe_list_shows_bundle_actions(client, app, user):
    login(client)

    response = client.get("/recipes")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Exportar todas" in body
    assert "Importar bundle" in body
    assert "/recipes/export-all" in body
    assert "/recipes/import-bundle" in body


def test_recipe_import_bundle_isolated_by_user(app, user):
    with app.app_context():
        other_user = _make_user("other-recipe-bundle-user")
        product = _make_product(other_user.id, "Other Bundle Product")
        document = _bundle_document_from_product(
            product,
            names=["Other User Bundle Recipe"],
        )
        source_file = _create_mock_source_file(app, other_user.id, document)

        try:
            import_recipe_bundle_file(source_file, user)
        except Exception as error:
            assert "does not belong to this user" in str(error)
        else:
            raise AssertionError("Expected import to fail for another user's file")