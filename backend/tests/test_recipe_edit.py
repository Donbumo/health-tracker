"""Tests for editing recipes."""

from decimal import Decimal

from app.extensions import db
from app.models import FoodProduct, Recipe, User
from app.services.recipes import create_recipe_from_products
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


def _make_recipe(user_id: int, product: FoodProduct, name: str = "Editable Recipe") -> Recipe:
    return create_recipe_from_products(
        user_id=user_id,
        name=name,
        description="Original description",
        servings=Decimal("2.000"),
        yield_weight_g=Decimal("500.000"),
        notes="Original notes",
        ingredients=[
            {
                "food_product_id": product.id,
                "quantity_g": Decimal("100.000"),
                "notes": "Original ingredient",
            }
        ],
    )


def test_recipe_edit_requires_login(client):
    response = client.get("/recipes/1/edit")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_recipe_edit_form_renders_existing_values(app, client, user):
    login(client)

    with app.app_context():
        product = _make_product(user, "Original Product")
        recipe = _make_recipe(user, product)
        db.session.commit()
        recipe_id = recipe.id

    response = client.get(f"/recipes/{recipe_id}/edit")
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    assert "Editar receta" in body
    assert "Editable Recipe" in body
    assert "Original Product" in body
    assert "Original ingredient" in body


def test_recipe_edit_updates_metadata_and_replaces_ingredients(app, client, user):
    login(client)

    with app.app_context():
        original_product = _make_product(
            user,
            "Original Product",
            calories_per_100g=Decimal("100.000"),
            protein_g_per_100g=Decimal("10.000"),
        )
        new_product = _make_product(
            user,
            "New Product",
            calories_per_100g=Decimal("400.000"),
            protein_g_per_100g=Decimal("80.000"),
            net_carbs_g_per_100g=Decimal("5.000"),
        )
        recipe = _make_recipe(user, original_product)
        db.session.commit()
        recipe_id = recipe.id
        new_product_id = new_product.id

    response = client.post(
        f"/recipes/{recipe_id}/edit",
        data={
            "name": "Updated Recipe",
            "description": "Updated description",
            "servings": "4",
            "yield_weight_g": "800",
            "notes": "Updated notes",
            "food_product_id[]": [str(new_product_id), ""],
            "quantity_g[]": ["200", ""],
            "ingredient_notes[]": ["Updated ingredient", ""],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Receta actualizada correctamente" in response.data

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert recipe.name == "Updated Recipe"
        assert recipe.description == "Updated description"
        assert recipe.servings == Decimal("4.000")
        assert recipe.yield_weight_g == Decimal("800.000")
        assert recipe.notes == "Updated notes"
        assert len(recipe.ingredients) == 1

        ingredient = recipe.ingredients[0]
        assert ingredient.food_product_id == new_product_id
        assert ingredient.name_snapshot == "New Product"
        assert ingredient.quantity_g == Decimal("200.000")
        assert ingredient.notes == "Updated ingredient"

        totals = recipe.totals()
        assert totals["calories"] == Decimal("800.000000")
        assert totals["protein_g"] == Decimal("160.000000")


def test_recipe_edit_rejects_duplicate_name_for_same_user(app, client, user):
    login(client)

    with app.app_context():
        product = _make_product(user, "Duplicate Product")
        existing_recipe = _make_recipe(user, product, name="Existing Recipe")
        editable_recipe = _make_recipe(user, product, name="Recipe To Edit")
        db.session.commit()
        existing_name = existing_recipe.name
        editable_id = editable_recipe.id
        product_id = product.id

    response = client.post(
        f"/recipes/{editable_id}/edit",
        data={
            "name": existing_name,
            "description": "Should not save",
            "servings": "1",
            "yield_weight_g": "100",
            "notes": "Should not save",
            "food_product_id[]": [str(product_id)],
            "quantity_g[]": ["100"],
            "ingredient_notes[]": [""],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Recipe name already exists for this user" in response.data

    with app.app_context():
        recipe = db.session.get(Recipe, editable_id)
        assert recipe.name == "Recipe To Edit"


def test_recipe_edit_isolated_by_user(app, client, user):
    login(client)

    with app.app_context():
        other_user = _make_user("other-recipe-edit-user")
        product = _make_product(other_user.id, "Other Product")
        recipe = _make_recipe(other_user.id, product, name="Other Recipe")
        db.session.commit()
        recipe_id = recipe.id

    response = client.get(f"/recipes/{recipe_id}/edit")
    assert response.status_code == 404