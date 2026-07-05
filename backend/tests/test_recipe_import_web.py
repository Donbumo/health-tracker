"""Web tests for recipe JSON import."""

import json
from decimal import Decimal
from io import BytesIO

from app.extensions import db
from app.models import FoodProduct, Recipe
from tests.conftest import login


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


def _json_upload(document: dict, filename: str = "recipe.json") -> tuple[BytesIO, str]:
    return BytesIO(json.dumps(document).encode("utf-8")), filename


def test_recipe_import_requires_login(client):
    response = client.get("/recipes/import")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_recipe_import_form_renders(client, app, user):
    with app.app_context():
        login(client)

    response = client.get("/recipes/import")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Importar receta" in body
    assert "Formato recomendado" in body


def test_recipe_import_web_upload_creates_recipe(client, app, user):
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
        db.session.commit()
        login(client)

        document = {
            "schema_version": "1.0",
            "type": "recipe",
            "name": "Receta importada web",
            "servings": 2,
            "yield_weight_g": 500,
            "source": "label_usuario",
            "ingredients": [
                {
                    "food_product_name": product.name,
                    "food_product_brand": product.brand,
                    "quantity_g": 40,
                }
            ],
        }

    response = client.post(
        "/recipes/import",
        data={"file": _json_upload(document)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/recipes/" in response.headers["Location"]

    with app.app_context():
        recipe = db.session.execute(
            db.select(Recipe).where(
                Recipe.user_id == user,
                Recipe.name == "Receta importada web",
            )
        ).scalar_one()

        assert recipe.source == "label_usuario"
        assert recipe.servings == Decimal("2.000")
        assert len(recipe.ingredients) == 1
        assert recipe.ingredients[0].name_snapshot == "Proteína XGear / Dr. Simi aislado"
        assert recipe.ingredients[0].quantity_g == Decimal("40.000")

    detail = client.get(response.headers["Location"])
    assert detail.status_code == 200
    body = detail.get_data(as_text=True)
    assert "Receta importada web" in body
    assert "Proteína XGear / Dr. Simi aislado" in body


def test_recipe_import_web_invalid_json_shows_error(client, app, user):
    with app.app_context():
        login(client)

    response = client.post(
        "/recipes/import",
        data={"file": (BytesIO(b"{bad json"), "bad_recipe.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Error al importar" in body