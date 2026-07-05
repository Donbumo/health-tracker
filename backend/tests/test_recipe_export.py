"""Tests for exporting recipes as portable JSON."""

import json
from decimal import Decimal

from app.extensions import db
from app.models import FoodProduct, Recipe, User
from app.services.exporters.recipe import build_recipe_export_document, recipe_export_bytes
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


def _make_recipe(user_id: int, product: FoodProduct, name: str = "Export Recipe") -> Recipe:
    return create_recipe_from_products(
        user_id=user_id,
        name=name,
        description="Export description",
        servings=Decimal("2.000"),
        yield_weight_g=Decimal("500.000"),
        notes="Export notes",
        ingredients=[
            {
                "food_product_id": product.id,
                "quantity_g": Decimal("125.000"),
                "notes": "Export ingredient notes",
            }
        ],
    )


def test_build_recipe_export_document_is_valid_portable_json(app, user):
    with app.app_context():
        product = _make_product(
            user,
            "Proteína Demo",
            brand="Marca Demo",
            calories_per_100g=Decimal("380.000"),
            protein_g_per_100g=Decimal("85.000"),
        )
        recipe = _make_recipe(user, product, name="Licuado exportable")
        db.session.commit()

        document = build_recipe_export_document(recipe)

        validate_json_document(document, "recipe")
        assert document["schema_version"] == "1.0"
        assert document["type"] == "recipe"
        assert document["name"] == "Licuado exportable"
        assert document["description"] == "Export description"
        assert document["servings"] == 2.0
        assert document["yield_weight_g"] == 500.0
        assert document["source"] == "manual"
        assert document["notes"] == "Export notes"

        ingredient = document["ingredients"][0]
        assert ingredient["food_product_name"] == "Proteína Demo"
        assert ingredient["food_product_brand"] == "Marca Demo"
        assert ingredient["quantity_g"] == 125.0
        assert ingredient["sort_order"] == 1
        assert ingredient["notes"] == "Export ingredient notes"
        assert "food_product_id" not in ingredient


def test_recipe_export_bytes_are_pretty_json(app, user):
    with app.app_context():
        product = _make_product(user, "Pretty JSON Product")
        recipe = _make_recipe(user, product)
        db.session.commit()

        payload = recipe_export_bytes(recipe)
        text = payload.decode("utf-8")
        document = json.loads(text)

        assert text.endswith("\n")
        assert '\n  "ingredients": [' in text
        assert document["name"] == "Export Recipe"
        validate_json_document(document, "recipe")


def test_recipe_export_route_requires_login(client):
    response = client.get("/recipes/1/export")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_recipe_export_route_downloads_json(app, client, user):
    login(client)

    with app.app_context():
        product = _make_product(user, "Download Product", brand="Download Brand")
        recipe = _make_recipe(user, product, name="Exportación Test")
        db.session.commit()
        recipe_id = recipe.id

    response = client.get(f"/recipes/{recipe_id}/export")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert "attachment;" in response.headers["Content-Disposition"]
    assert response.headers["Content-Disposition"].endswith('.json"')

    document = json.loads(response.data.decode("utf-8"))
    validate_json_document(document, "recipe")
    assert document["name"] == "Exportación Test"
    assert document["ingredients"][0]["food_product_name"] == "Download Product"
    assert document["ingredients"][0]["food_product_brand"] == "Download Brand"


def test_recipe_detail_shows_export_action(app, client, user):
    login(client)

    with app.app_context():
        product = _make_product(user, "Export Button Product")
        recipe = _make_recipe(user, product)
        db.session.commit()
        recipe_id = recipe.id

    response = client.get(f"/recipes/{recipe_id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert "Exportar JSON" in body
    assert f"/recipes/{recipe_id}/export" in body


def test_recipe_export_isolated_by_user(app, client, user):
    login(client)

    with app.app_context():
        other_user = _make_user("other-recipe-export-user")
        product = _make_product(other_user.id, "Other Export Product")
        recipe = _make_recipe(other_user.id, product, name="Other Export Recipe")
        db.session.commit()
        recipe_id = recipe.id

    response = client.get(f"/recipes/{recipe_id}/export")
    assert response.status_code == 404