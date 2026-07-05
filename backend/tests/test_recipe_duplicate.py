"""Tests for duplicating recipes into editable variants."""

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


def _make_recipe(user_id: int, product: FoodProduct, name: str = "Base Recipe") -> Recipe:
    return create_recipe_from_products(
        user_id=user_id,
        name=name,
        description="Base description",
        servings=Decimal("2.000"),
        yield_weight_g=Decimal("500.000"),
        notes="Base notes",
        ingredients=[
            {
                "food_product_id": product.id,
                "quantity_g": Decimal("100.000"),
                "notes": "Base ingredient",
            }
        ],
    )


def test_recipe_duplicate_requires_login(client):
    response = client.post("/recipes/1/duplicate")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_recipe_detail_shows_duplicate_action(app, client, user):
    login(client)

    with app.app_context():
        product = _make_product(user, "Duplicate Button Product")
        recipe = _make_recipe(user, product)
        db.session.commit()
        recipe_id = recipe.id

    response = client.get(f"/recipes/{recipe_id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Duplicar" in body
    assert f"/recipes/{recipe_id}/duplicate" in body


def test_recipe_duplicate_creates_editable_variant_with_fresh_snapshots(
    app,
    client,
    user,
):
    login(client)

    with app.app_context():
        product = _make_product(
            user,
            "Original Product",
            calories_per_100g=Decimal("100.000"),
            protein_g_per_100g=Decimal("10.000"),
            net_carbs_g_per_100g=Decimal("2.000"),
        )
        recipe = _make_recipe(user, product, name="Protein Base")
        product.name = "Updated Product"
        product.calories_per_100g = Decimal("500.000")
        product.protein_g_per_100g = Decimal("50.000")
        product.net_carbs_g_per_100g = Decimal("5.000")
        db.session.commit()
        recipe_id = recipe.id

    response = client.post(
        f"/recipes/{recipe_id}/duplicate",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/recipes/" in response.headers["Location"]
    assert "/edit" in response.headers["Location"]

    with app.app_context():
        recipes = db.session.execute(
            db.select(Recipe)
            .where(Recipe.user_id == user)
            .order_by(Recipe.id.asc())
        ).scalars().all()

        assert len(recipes) == 2
        original = recipes[0]
        duplicate = recipes[1]

        assert original.name == "Protein Base"
        assert duplicate.name == "Protein Base (copia)"
        assert duplicate.description == "Base description"
        assert duplicate.servings == Decimal("2.000")
        assert duplicate.yield_weight_g == Decimal("500.000")
        assert duplicate.notes == "Base notes"
        assert len(duplicate.ingredients) == 1

        ingredient = duplicate.ingredients[0]
        assert ingredient.name_snapshot == "Updated Product"
        assert ingredient.calories_per_100g == Decimal("500.000")
        assert ingredient.protein_g_per_100g == Decimal("50.000")
        assert ingredient.net_carbs_g_per_100g == Decimal("5.000")
        assert ingredient.quantity_g == Decimal("100.000")

        totals = duplicate.totals()
        assert totals["calories"] == Decimal("500.000000")
        assert totals["protein_g"] == Decimal("50.000000")


def test_recipe_duplicate_generates_incrementing_copy_names(app, client, user):
    login(client)

    with app.app_context():
        product = _make_product(user, "Copy Name Product")
        recipe = _make_recipe(user, product, name="Variant Base")
        db.session.commit()
        recipe_id = recipe.id

    first = client.post(f"/recipes/{recipe_id}/duplicate")
    second = client.post(f"/recipes/{recipe_id}/duplicate")

    assert first.status_code == 302
    assert second.status_code == 302

    with app.app_context():
        names = {
            recipe.name
            for recipe in db.session.execute(
                db.select(Recipe).where(Recipe.user_id == user)
            ).scalars()
        }

        assert "Variant Base" in names
        assert "Variant Base (copia)" in names
        assert "Variant Base (copia 2)" in names


def test_recipe_duplicate_rejects_inactive_product(app, client, user):
    login(client)

    with app.app_context():
        product = _make_product(user, "Inactive Duplicate Product")
        recipe = _make_recipe(user, product, name="Inactive Product Recipe")
        product.is_active = False
        db.session.commit()
        recipe_id = recipe.id

    response = client.post(
        f"/recipes/{recipe_id}/duplicate",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"No fue posible duplicar receta" in response.data

    with app.app_context():
        recipes = db.session.execute(
            db.select(Recipe).where(Recipe.user_id == user)
        ).scalars().all()
        assert len(recipes) == 1


def test_recipe_duplicate_isolated_by_user(app, client, user):
    login(client)

    with app.app_context():
        other_user = _make_user("other-recipe-duplicate-user")
        product = _make_product(other_user.id, "Other Duplicate Product")
        recipe = _make_recipe(other_user.id, product, name="Other Duplicate Recipe")
        db.session.commit()
        recipe_id = recipe.id

    response = client.post(f"/recipes/{recipe_id}/duplicate")
    assert response.status_code == 404