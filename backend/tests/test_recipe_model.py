"""Tests for Recipe and RecipeIngredient models."""

from decimal import Decimal, ROUND_HALF_UP

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import FoodProduct, Recipe, RecipeIngredient, User


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
    product = FoodProduct(
        user_id=user_id,
        name=name,
        **defaults,
    )
    db.session.add(product)
    db.session.flush()
    return product


def _make_recipe(
    user_id: int,
    name: str = "Demo Recipe",
    servings: Decimal = Decimal("5.000"),
    yield_weight_g: Decimal | None = Decimal("300.000"),
) -> Recipe:
    recipe = Recipe(
        user_id=user_id,
        name=name,
        servings=servings,
        yield_weight_g=yield_weight_g,
        source="manual",
    )
    db.session.add(recipe)
    db.session.flush()
    return recipe


def _add_ingredient_from_product(
    recipe: Recipe,
    product: FoodProduct,
    quantity_g: Decimal,
    sort_order: int = 1,
    **overrides,
) -> RecipeIngredient:
    values = {
        "user_id": recipe.user_id,
        "recipe": recipe,
        "food_product_id": product.id,
        "name_snapshot": product.name,
        "brand_snapshot": product.brand,
        "quantity_g": quantity_g,
        "sort_order": sort_order,
        "calories_per_100g": product.calories_per_100g,
        "protein_g_per_100g": product.protein_g_per_100g,
        "fat_g_per_100g": product.fat_g_per_100g,
        "carbs_g_per_100g": product.carbs_g_per_100g,
        "net_carbs_g_per_100g": product.net_carbs_g_per_100g,
        "fiber_g_per_100g": product.fiber_g_per_100g,
        "sodium_mg_per_100g": product.sodium_mg_per_100g,
    }
    values.update(overrides)
    ingredient = RecipeIngredient(**values)
    db.session.add(ingredient)
    db.session.flush()
    return ingredient


def test_recipe_calculates_totals_per_serving_and_per_100g(app, user):
    with app.app_context():
        flour = _make_product(
            user,
            "Almond Flour",
            brand="FictionalBrand",
            calories_per_100g=Decimal("300.000"),
            protein_g_per_100g=Decimal("20.000"),
            fat_g_per_100g=Decimal("10.000"),
            carbs_g_per_100g=Decimal("30.000"),
            net_carbs_g_per_100g=Decimal("20.000"),
            fiber_g_per_100g=Decimal("10.000"),
            sodium_mg_per_100g=Decimal("100.000"),
        )
        yogurt = _make_product(
            user,
            "Greek Yogurt",
            brand="FictionalBrand",
            calories_per_100g=Decimal("60.000"),
            protein_g_per_100g=Decimal("10.000"),
            fat_g_per_100g=Decimal("2.000"),
            carbs_g_per_100g=Decimal("5.000"),
            net_carbs_g_per_100g=Decimal("5.000"),
            fiber_g_per_100g=Decimal("0.000"),
            sodium_mg_per_100g=Decimal("40.000"),
        )
        recipe = _make_recipe(
            user,
            "Protein Pancakes",
            servings=Decimal("5.000"),
            yield_weight_g=Decimal("300.000"),
        )
        _add_ingredient_from_product(
            recipe,
            flour,
            quantity_g=Decimal("200.000"),
            sort_order=1,
        )
        _add_ingredient_from_product(
            recipe,
            yogurt,
            quantity_g=Decimal("100.000"),
            sort_order=2,
        )

        totals = recipe.totals()
        _assert_decimal(totals["calories"], "660.000")
        _assert_decimal(totals["protein_g"], "50.000")
        _assert_decimal(totals["fat_g"], "22.000")
        _assert_decimal(totals["total_carbs_g"], "65.000")
        _assert_decimal(totals["net_carbs_g"], "45.000")
        _assert_decimal(totals["fiber_g"], "20.000")
        _assert_decimal(totals["sodium_mg"], "240.000")

        per_serving = recipe.per_serving()
        _assert_decimal(per_serving["calories"], "132.000")
        _assert_decimal(per_serving["protein_g"], "10.000")
        _assert_decimal(per_serving["fat_g"], "4.400")
        _assert_decimal(per_serving["total_carbs_g"], "13.000")
        _assert_decimal(per_serving["net_carbs_g"], "9.000")
        _assert_decimal(per_serving["fiber_g"], "4.000")
        _assert_decimal(per_serving["sodium_mg"], "48.000")

        per_100g = recipe.per_100g()
        _assert_decimal(per_100g["calories"], "220.000")
        _assert_decimal(per_100g["protein_g"], "16.667")
        _assert_decimal(per_100g["fat_g"], "7.333")
        _assert_decimal(per_100g["total_carbs_g"], "21.667")
        _assert_decimal(per_100g["net_carbs_g"], "15.000")
        _assert_decimal(per_100g["fiber_g"], "6.667")
        _assert_decimal(per_100g["sodium_mg"], "80.000")


def test_recipe_missing_metric_returns_none_only_for_that_metric(app, user):
    with app.app_context():
        product = _make_product(
            user,
            "Partial Macro Product",
            net_carbs_g_per_100g=None,
        )
        recipe = _make_recipe(user, "Partial Macro Recipe")
        _add_ingredient_from_product(
            recipe,
            product,
            quantity_g=Decimal("100.000"),
        )

        totals = recipe.totals()
        _assert_decimal(totals["calories"], "300.000")
        _assert_decimal(totals["protein_g"], "20.000")
        assert totals["net_carbs_g"] is None


def test_recipe_per_100g_returns_none_without_yield_weight(app, user):
    with app.app_context():
        product = _make_product(user, "No Yield Product")
        recipe = _make_recipe(
            user,
            "No Yield Recipe",
            servings=Decimal("2.000"),
            yield_weight_g=None,
        )
        _add_ingredient_from_product(
            recipe,
            product,
            quantity_g=Decimal("100.000"),
        )

        per_100g = recipe.per_100g()
        assert all(value is None for value in per_100g.values())


def test_recipe_ingredient_snapshot_does_not_change_when_product_changes(app, user):
    with app.app_context():
        product = _make_product(
            user,
            "Protein Powder",
            calories_per_100g=Decimal("400.000"),
            protein_g_per_100g=Decimal("80.000"),
        )
        recipe = _make_recipe(user, "Protein Shake")
        ingredient = _add_ingredient_from_product(
            recipe,
            product,
            quantity_g=Decimal("50.000"),
        )

        product.protein_g_per_100g = Decimal("90.000")
        product.calories_per_100g = Decimal("450.000")
        db.session.flush()

        assert ingredient.protein_g_per_100g == Decimal("80.000")
        assert ingredient.calories_per_100g == Decimal("400.000")

        totals = recipe.totals()
        _assert_decimal(totals["protein_g"], "40.000")
        _assert_decimal(totals["calories"], "200.000")


def test_recipe_unique_name_per_user(app, user):
    with app.app_context():
        _make_recipe(user, "Same Recipe Name")
        with pytest.raises(IntegrityError):
            _make_recipe(user, "Same Recipe Name")
            db.session.flush()


def test_recipe_same_name_different_user_is_allowed(app, user):
    with app.app_context():
        second = _make_user("second-recipe-user")
        _make_recipe(user, "Shared Recipe")
        _make_recipe(second.id, "Shared Recipe")
        db.session.commit()

        count = db.session.execute(db.select(db.func.count(Recipe.id))).scalar_one()
        assert count == 2