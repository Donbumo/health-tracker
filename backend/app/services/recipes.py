from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from app.extensions import db
from app.models import FoodProduct, Recipe, RecipeIngredient


class RecipeServiceError(ValueError):
    pass


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if not text:
        raise RecipeServiceError(f"{field_name} must not be blank")
    return text


def _positive_decimal(value: Any, field_name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise RecipeServiceError(f"{field_name} must be a valid number") from error

    if number <= 0:
        raise RecipeServiceError(f"{field_name} must be greater than zero")
    return number


def _food_product_id(value: Any) -> int:
    try:
        product_id = int(value)
    except (TypeError, ValueError) as error:
        raise RecipeServiceError("food_product_id must be a valid integer") from error

    if product_id <= 0:
        raise RecipeServiceError("food_product_id must be greater than zero")
    return product_id


def _sort_order(value: Any, default: int) -> int:
    if value is None:
        return default

    try:
        sort_order = int(value)
    except (TypeError, ValueError) as error:
        raise RecipeServiceError("sort_order must be a valid integer") from error

    if sort_order < 1:
        raise RecipeServiceError("sort_order must be greater than or equal to one")
    return sort_order


def _get_product_for_user(user_id: int, product_id: int) -> FoodProduct:
    product = db.session.execute(
        db.select(FoodProduct).where(
            FoodProduct.id == product_id,
            FoodProduct.user_id == user_id,
        )
    ).scalar_one_or_none()

    if product is None:
        raise RecipeServiceError("Food product not found for this user")
    if not product.is_active:
        raise RecipeServiceError("Food product is inactive")
    return product


def _validate_recipe_name_available(
    *,
    user_id: int,
    recipe_name: str,
    current_recipe_id: int | None = None,
) -> None:
    query = db.select(Recipe).where(
        Recipe.user_id == user_id,
        Recipe.name == recipe_name,
    )
    if current_recipe_id is not None:
        query = query.where(Recipe.id != current_recipe_id)

    existing = db.session.execute(query).scalar_one_or_none()
    if existing is not None:
        raise RecipeServiceError("Recipe name already exists for this user")


def _validated_ingredient_specs(
    *,
    user_id: int,
    ingredients: Iterable[dict[str, Any]],
) -> list[tuple[FoodProduct, Decimal, int, str | None]]:
    ingredient_specs = list(ingredients)
    if not ingredient_specs:
        raise RecipeServiceError("Recipe must have at least one ingredient")

    validated_ingredients: list[tuple[FoodProduct, Decimal, int, str | None]] = []
    seen_sort_orders: set[int] = set()

    for index, spec in enumerate(ingredient_specs, start=1):
        product_id = _food_product_id(spec.get("food_product_id"))
        product = _get_product_for_user(user_id, product_id)
        quantity_g = _positive_decimal(spec.get("quantity_g"), "quantity_g")
        sort_order = _sort_order(spec.get("sort_order"), index)

        if sort_order in seen_sort_orders:
            raise RecipeServiceError("Recipe ingredient sort_order values must be unique")
        seen_sort_orders.add(sort_order)

        validated_ingredients.append(
            (
                product,
                quantity_g,
                sort_order,
                _optional_text(spec.get("notes")),
            )
        )

    return validated_ingredients


def recipe_ingredient_from_product(
    *,
    user_id: int,
    recipe: Recipe,
    product: FoodProduct,
    quantity_g: Decimal,
    sort_order: int,
    notes: str | None = None,
) -> RecipeIngredient:
    """Create a recipe ingredient snapshot from a FoodProduct."""
    if product.user_id != user_id:
        raise RecipeServiceError("Food product does not belong to this user")
    if not product.is_active:
        raise RecipeServiceError("Food product is inactive")

    return RecipeIngredient(
        user_id=user_id,
        recipe=recipe,
        food_product_id=product.id,
        name_snapshot=product.name,
        brand_snapshot=product.brand,
        quantity_g=quantity_g,
        sort_order=sort_order,
        calories_per_100g=product.calories_per_100g,
        protein_g_per_100g=product.protein_g_per_100g,
        fat_g_per_100g=product.fat_g_per_100g,
        carbs_g_per_100g=product.carbs_g_per_100g,
        net_carbs_g_per_100g=product.net_carbs_g_per_100g,
        fiber_g_per_100g=product.fiber_g_per_100g,
        sodium_mg_per_100g=product.sodium_mg_per_100g,
        notes=notes,
    )


def create_recipe_from_products(
    *,
    user_id: int,
    name: str,
    ingredients: Iterable[dict[str, Any]],
    servings: Any = Decimal("1"),
    yield_weight_g: Any = None,
    description: str | None = None,
    source: str = "manual",
    notes: str | None = None,
    raw_payload_json: dict[str, Any] | None = None,
    commit: bool = True,
) -> Recipe:
    """Create a Recipe and ingredient snapshots from FoodProduct IDs."""
    recipe_name = _required_text(name, "name")
    recipe_source = _required_text(source, "source")
    recipe_servings = _positive_decimal(servings, "servings")
    recipe_yield_weight_g = (
        _positive_decimal(yield_weight_g, "yield_weight_g")
        if yield_weight_g is not None
        else None
    )

    _validate_recipe_name_available(user_id=user_id, recipe_name=recipe_name)

    validated_ingredients = _validated_ingredient_specs(
        user_id=user_id,
        ingredients=ingredients,
    )

    recipe = Recipe(
        user_id=user_id,
        name=recipe_name,
        description=_optional_text(description),
        servings=recipe_servings,
        yield_weight_g=recipe_yield_weight_g,
        source=recipe_source,
        notes=_optional_text(notes),
        raw_payload_json=raw_payload_json,
    )
    db.session.add(recipe)

    for product, quantity_g, sort_order, ingredient_notes in validated_ingredients:
        db.session.add(
            recipe_ingredient_from_product(
                user_id=user_id,
                recipe=recipe,
                product=product,
                quantity_g=quantity_g,
                sort_order=sort_order,
                notes=ingredient_notes,
            )
        )

    if commit:
        db.session.commit()
    else:
        db.session.flush()

    return recipe


def update_recipe_from_products(
    *,
    user_id: int,
    recipe: Recipe,
    name: str,
    ingredients: Iterable[dict[str, Any]],
    servings: Any = Decimal("1"),
    yield_weight_g: Any = None,
    description: str | None = None,
    notes: str | None = None,
    commit: bool = True,
) -> Recipe:
    """Update recipe metadata and replace ingredient snapshots.

    Historical daily nutrition items keep their own macro snapshots and are not
    recalculated when a recipe changes.
    """
    if recipe.user_id != user_id:
        raise RecipeServiceError("Recipe does not belong to this user")

    recipe_name = _required_text(name, "name")
    recipe_servings = _positive_decimal(servings, "servings")
    recipe_yield_weight_g = (
        _positive_decimal(yield_weight_g, "yield_weight_g")
        if yield_weight_g is not None
        else None
    )

    _validate_recipe_name_available(
        user_id=user_id,
        recipe_name=recipe_name,
        current_recipe_id=recipe.id,
    )

    validated_ingredients = _validated_ingredient_specs(
        user_id=user_id,
        ingredients=ingredients,
    )

    recipe.name = recipe_name
    recipe.description = _optional_text(description)
    recipe.servings = recipe_servings
    recipe.yield_weight_g = recipe_yield_weight_g
    recipe.notes = _optional_text(notes)

    for ingredient in list(recipe.ingredients):
        db.session.delete(ingredient)
    db.session.flush()

    for product, quantity_g, sort_order, ingredient_notes in validated_ingredients:
        db.session.add(
            recipe_ingredient_from_product(
                user_id=user_id,
                recipe=recipe,
                product=product,
                quantity_g=quantity_g,
                sort_order=sort_order,
                notes=ingredient_notes,
            )
        )

    if commit:
        db.session.commit()
    else:
        db.session.flush()

    return recipe