from decimal import Decimal, InvalidOperation

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import FoodProduct, Recipe
from app.recipes import recipes_bp
from app.recipes.forms import RecipeForm
from app.services.recipes import RecipeServiceError, create_recipe_from_products


def _active_food_products():
    return db.session.execute(
        db.select(FoodProduct)
        .where(
            FoodProduct.user_id == current_user.id,
            FoodProduct.is_active.is_(True),
        )
        .order_by(FoodProduct.name.asc())
    ).scalars().all()


def _recipe_for_user(recipe_id: int) -> Recipe:
    recipe = db.session.execute(
        db.select(Recipe)
        .options(selectinload(Recipe.ingredients))
        .where(
            Recipe.id == recipe_id,
            Recipe.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if recipe is None:
        abort(404)
    return recipe


def _parse_decimal(value: str, field_name: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError) as error:
        raise RecipeServiceError(f"{field_name} debe ser un número válido") from error

    if number <= 0:
        raise RecipeServiceError(f"{field_name} debe ser mayor que cero")
    return number


def _ingredient_specs_from_form() -> list[dict]:
    product_ids = request.form.getlist("food_product_id[]")
    quantities = request.form.getlist("quantity_g[]")
    notes = request.form.getlist("ingredient_notes[]")

    specs = []
    for index, product_id in enumerate(product_ids):
        quantity = quantities[index] if index < len(quantities) else ""
        note = notes[index] if index < len(notes) else ""

        product_id = product_id.strip()
        quantity = quantity.strip()

        if not product_id and not quantity:
            continue
        if not product_id or not quantity:
            raise RecipeServiceError(
                "Cada ingrediente debe tener producto y cantidad."
            )

        specs.append(
            {
                "food_product_id": int(product_id),
                "quantity_g": _parse_decimal(quantity, "quantity_g"),
                "sort_order": len(specs) + 1,
                "notes": note.strip() or None,
            }
        )

    if not specs:
        raise RecipeServiceError("La receta debe tener al menos un ingrediente.")

    return specs


def _recipe_summary(recipe: Recipe) -> dict:
    return {
        "recipe": recipe,
        "totals": recipe.totals(),
        "per_serving": recipe.per_serving(),
        "per_100g": recipe.per_100g(),
    }


@recipes_bp.route("")
@login_required
def list_recipes():
    recipes = db.session.execute(
        db.select(Recipe)
        .options(selectinload(Recipe.ingredients))
        .where(Recipe.user_id == current_user.id)
        .order_by(Recipe.name.asc())
    ).scalars().all()

    records = [_recipe_summary(recipe) for recipe in recipes]
    return render_template("recipes/list.html", records=records)


@recipes_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_recipe():
    form = RecipeForm()
    products = _active_food_products()

    if form.validate_on_submit():
        try:
            recipe = create_recipe_from_products(
                user_id=current_user.id,
                name=form.name.data,
                description=form.description.data,
                servings=form.servings.data,
                yield_weight_g=form.yield_weight_g.data,
                notes=form.notes.data,
                source="manual",
                ingredients=_ingredient_specs_from_form(),
            )
            flash("Receta guardada correctamente.", "success")
            return redirect(url_for("recipes.detail_recipe", id=recipe.id))
        except (RecipeServiceError, ValueError) as error:
            db.session.rollback()
            flash(f"Error al guardar receta: {error}", "error")

    return render_template("recipes/new.html", form=form, products=products)


@recipes_bp.route("/<int:id>")
@login_required
def detail_recipe(id: int):
    recipe = _recipe_for_user(id)
    return render_template(
        "recipes/detail.html",
        recipe=recipe,
        totals=recipe.totals(),
        per_serving=recipe.per_serving(),
        per_100g=recipe.per_100g(),
    )