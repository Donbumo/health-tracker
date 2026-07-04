from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db


RECIPE_METRIC_FIELDS = (
    "calories_per_100g",
    "protein_g_per_100g",
    "fat_g_per_100g",
    "carbs_g_per_100g",
    "net_carbs_g_per_100g",
    "fiber_g_per_100g",
    "sodium_mg_per_100g",
)


def _metric_constraints(prefix: str) -> tuple[db.CheckConstraint, ...]:
    return tuple(
        db.CheckConstraint(
            f"{field} IS NULL OR {field} >= 0",
            name=f"ck_{prefix}_{field}",
        )
        for field in RECIPE_METRIC_FIELDS
    )


def _scale_per_100g(value: Decimal | None, quantity_g: Decimal) -> Decimal | None:
    if value is None:
        return None
    return value * quantity_g / Decimal("100")


def _sum_metric(values: list[Decimal | None]) -> Decimal | None:
    if any(value is None for value in values):
        return None
    return sum(values, Decimal("0"))


class Recipe(db.Model):
    """User-owned recipe made from food products or macro snapshots."""

    __tablename__ = "recipes"
    __table_args__ = (
        db.CheckConstraint("servings > 0", name="ck_recipes_servings_positive"),
        db.CheckConstraint(
            "yield_weight_g IS NULL OR yield_weight_g > 0",
            name="ck_recipes_yield_weight_positive",
        ),
        db.UniqueConstraint("user_id", "name", name="uq_recipes_user_name"),
        db.Index("ix_recipes_user_active", "user_id", "is_active"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    servings = db.Column(
        db.Numeric(10, 3),
        nullable=False,
        default=1,
        server_default="1",
    )
    yield_weight_g = db.Column(db.Numeric(12, 3), nullable=True)
    source = db.Column(
        db.String(32),
        nullable=False,
        default="manual",
        server_default="manual",
    )
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    raw_payload_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User", back_populates="recipes")
    ingredients = db.relationship(
        "RecipeIngredient",
        back_populates="recipe",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RecipeIngredient.sort_order",
    )

    def totals(self) -> dict[str, Decimal | None]:
        """Return recipe totals calculated from ingredient macro snapshots."""
        return {
            "calories": _sum_metric(
                [
                    _scale_per_100g(ingredient.calories_per_100g, ingredient.quantity_g)
                    for ingredient in self.ingredients
                ]
            ),
            "protein_g": _sum_metric(
                [
                    _scale_per_100g(ingredient.protein_g_per_100g, ingredient.quantity_g)
                    for ingredient in self.ingredients
                ]
            ),
            "fat_g": _sum_metric(
                [
                    _scale_per_100g(ingredient.fat_g_per_100g, ingredient.quantity_g)
                    for ingredient in self.ingredients
                ]
            ),
            "total_carbs_g": _sum_metric(
                [
                    _scale_per_100g(ingredient.carbs_g_per_100g, ingredient.quantity_g)
                    for ingredient in self.ingredients
                ]
            ),
            "net_carbs_g": _sum_metric(
                [
                    _scale_per_100g(
                        ingredient.net_carbs_g_per_100g,
                        ingredient.quantity_g,
                    )
                    for ingredient in self.ingredients
                ]
            ),
            "fiber_g": _sum_metric(
                [
                    _scale_per_100g(ingredient.fiber_g_per_100g, ingredient.quantity_g)
                    for ingredient in self.ingredients
                ]
            ),
            "sodium_mg": _sum_metric(
                [
                    _scale_per_100g(ingredient.sodium_mg_per_100g, ingredient.quantity_g)
                    for ingredient in self.ingredients
                ]
            ),
        }

    def per_serving(self) -> dict[str, Decimal | None]:
        totals = self.totals()
        return {
            metric: value / self.servings if value is not None else None
            for metric, value in totals.items()
        }

    def per_100g(self) -> dict[str, Decimal | None]:
        totals = self.totals()
        if self.yield_weight_g is None:
            return {metric: None for metric in totals}

        return {
            metric: value * Decimal("100") / self.yield_weight_g
            if value is not None
            else None
            for metric, value in totals.items()
        }


class RecipeIngredient(db.Model):
    """Ingredient row with product identity and macro snapshots."""

    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        *_metric_constraints("recipe_ingredients"),
        db.CheckConstraint("quantity_g > 0", name="ck_recipe_ingredients_quantity"),
        db.CheckConstraint("sort_order >= 1", name="ck_recipe_ingredients_sort_order"),
        db.UniqueConstraint(
            "recipe_id",
            "sort_order",
            name="uq_recipe_ingredients_recipe_order",
        ),
        db.Index("ix_recipe_ingredients_user_recipe", "user_id", "recipe_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipe_id = db.Column(
        db.Integer,
        db.ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=False,
    )
    food_product_id = db.Column(
        db.Integer,
        db.ForeignKey("food_products.id", ondelete="SET NULL"),
        nullable=True,
    )
    name_snapshot = db.Column(db.String(200), nullable=False)
    brand_snapshot = db.Column(db.String(200), nullable=True)
    quantity_g = db.Column(db.Numeric(12, 3), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False)
    calories_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    protein_g_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    fat_g_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    carbs_g_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    net_carbs_g_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    fiber_g_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    sodium_mg_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    recipe = db.relationship("Recipe", back_populates="ingredients")
    food_product = db.relationship("FoodProduct")