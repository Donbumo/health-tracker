"""Tests for recipe service helpers."""

from decimal import Decimal, ROUND_HALF_UP

import pytest

from app.extensions import db
from app.models import FoodProduct, Recipe, User
from app.services.recipes import RecipeServiceError, create_recipe_from_products


def _q(value: Decimal | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def _assert_decimal(actual, expected: str) -> None:
    assert actual is not None
    assert _q(actual) == _q(expected)


def _make_user(username: str) -> User:
    user = User(username=username, role="user")
    user.set_password("test-password")
    db.session.add(user)
    db.session.flush()
    return user


def _make_product(user_id: int, name: str = "Demo Product", **kwargs) -> FoodProduct:
    defaults = {
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


def test_create_recipe_from_products_creates_snapshots_and_calculates_macros(app, user):
    with app.app_context():
        protein = _make_product(
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
        milk = _make_product(
            user,
            "Leche almendra Member's Mark vainilla sin endulzar",
            brand="Member's Mark",
            calories_per_100g=Decimal("12.200"),
            protein_g_per_100g=Decimal("0.400"),
            fat_g_per_100g=Decimal("1.000"),
            carbs_g_per_100g=Decimal("0.400"),
            net_carbs_g_per_100g=Decimal("0.400"),
            fiber_g_per_100g=Decimal("0.400"),
            sodium_mg_per_100g=Decimal("78.000"),
        )

        recipe = create_recipe_from_products(
            user_id=user,
            name="Licuado de proteína",
            servings=Decimal("2.000"),
            yield_weight_g=Decimal("500.000"),
            description="Receta de prueba.",
            ingredients=[
                {
                    "food_product_id": protein.id,
                    "quantity_g": Decimal("40.000"),
                    "sort_order": 1,
                },
                {
                    "food_product_id": milk.id,
                    "quantity_g": Decimal("100.000"),
                    "sort_order": 2,
                    "notes": "Usar fría.",
                },
            ],
        )

        assert recipe.id is not None
        assert recipe.name == "Licuado de proteína"
        assert recipe.servings == Decimal("2.000")
        assert len(recipe.ingredients) == 2

        first = recipe.ingredients[0]
        assert first.name_snapshot == "Proteína XGear / Dr. Simi aislado"
        assert first.brand_snapshot == "XGear / Dr. Simi"
        assert first.food_product_id == protein.id
        assert first.protein_g_per_100g == Decimal("85.000")

        second = recipe.ingredients[1]
        assert second.name_snapshot == "Leche almendra Member's Mark vainilla sin endulzar"
        assert second.notes == "Usar fría."

        totals = recipe.totals()
        _assert_decimal(totals["calories"], "164.200")
        _assert_decimal(totals["protein_g"], "34.400")
        _assert_decimal(totals["fat_g"], "1.800")
        _assert_decimal(totals["total_carbs_g"], "0.400")
        _assert_decimal(totals["net_carbs_g"], "0.400")
        _assert_decimal(totals["fiber_g"], "0.400")
        _assert_decimal(totals["sodium_mg"], "118.000")

        per_serving = recipe.per_serving()
        _assert_decimal(per_serving["calories"], "82.100")
        _assert_decimal(per_serving["protein_g"], "17.200")
        _assert_decimal(per_serving["net_carbs_g"], "0.200")

        per_100g = recipe.per_100g()
        _assert_decimal(per_100g["calories"], "32.840")
        _assert_decimal(per_100g["protein_g"], "6.880")
        _assert_decimal(per_100g["net_carbs_g"], "0.080")


def test_create_recipe_rejects_other_users_product(app, user):
    with app.app_context():
        second = _make_user("recipe-service-second-user")
        other_product = _make_product(second.id, "Other User Product")

        with pytest.raises(RecipeServiceError) as exc:
            create_recipe_from_products(
                user_id=user,
                name="Invalid Recipe",
                ingredients=[
                    {
                        "food_product_id": other_product.id,
                        "quantity_g": Decimal("100.000"),
                    }
                ],
            )

        assert "not found for this user" in str(exc.value)


def test_create_recipe_rejects_inactive_product(app, user):
    with app.app_context():
        product = _make_product(user, "Inactive Product", is_active=False)

        with pytest.raises(RecipeServiceError) as exc:
            create_recipe_from_products(
                user_id=user,
                name="Inactive Product Recipe",
                ingredients=[
                    {
                        "food_product_id": product.id,
                        "quantity_g": Decimal("100.000"),
                    }
                ],
            )

        assert "inactive" in str(exc.value)


def test_create_recipe_validates_required_inputs(app, user):
    with app.app_context():
        product = _make_product(user, "Validation Product")

        with pytest.raises(RecipeServiceError):
            create_recipe_from_products(
                user_id=user,
                name="",
                ingredients=[
                    {
                        "food_product_id": product.id,
                        "quantity_g": Decimal("100.000"),
                    }
                ],
            )

        with pytest.raises(RecipeServiceError):
            create_recipe_from_products(
                user_id=user,
                name="No Ingredients",
                ingredients=[],
            )

        with pytest.raises(RecipeServiceError):
            create_recipe_from_products(
                user_id=user,
                name="Bad Quantity",
                ingredients=[
                    {
                        "food_product_id": product.id,
                        "quantity_g": Decimal("0.000"),
                    }
                ],
            )

        with pytest.raises(RecipeServiceError):
            create_recipe_from_products(
                user_id=user,
                name="Bad Servings",
                servings=Decimal("0.000"),
                ingredients=[
                    {
                        "food_product_id": product.id,
                        "quantity_g": Decimal("100.000"),
                    }
                ],
            )


def test_create_recipe_rejects_duplicate_name_for_user(app, user):
    with app.app_context():
        product = _make_product(user, "Duplicate Recipe Product")

        create_recipe_from_products(
            user_id=user,
            name="Duplicate Recipe",
            ingredients=[
                {
                    "food_product_id": product.id,
                    "quantity_g": Decimal("100.000"),
                }
            ],
        )

        with pytest.raises(RecipeServiceError) as exc:
            create_recipe_from_products(
                user_id=user,
                name="Duplicate Recipe",
                ingredients=[
                    {
                        "food_product_id": product.id,
                        "quantity_g": Decimal("50.000"),
                    }
                ],
            )

        assert "already exists" in str(exc.value)


def test_create_recipe_can_flush_without_commit(app, user):
    with app.app_context():
        product = _make_product(user, "Flush Product")

        recipe = create_recipe_from_products(
            user_id=user,
            name="Flush Recipe",
            ingredients=[
                {
                    "food_product_id": product.id,
                    "quantity_g": Decimal("100.000"),
                }
            ],
            commit=False,
        )

        assert recipe.id is not None
        count = db.session.execute(db.select(db.func.count(Recipe.id))).scalar_one()
        assert count == 1