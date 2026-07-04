from datetime import datetime, timezone

from app.extensions import db


NUTRITION_METRICS = (
    "calories",
    "protein_g",
    "fat_g",
    "net_carbs_g",
    "total_carbs_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
)


def _metric_constraints(prefix: str) -> tuple[db.CheckConstraint, ...]:
    return tuple(
        db.CheckConstraint(
            f"{field} IS NULL OR {field} >= 0",
            name=f"ck_{prefix}_{field}",
        )
        for field in NUTRITION_METRICS
    )


class DailyNutrition(db.Model):
    __tablename__ = "daily_nutrition"
    __table_args__ = (
        *_metric_constraints("daily_nutrition"),
        db.UniqueConstraint(
            "user_id",
            "date",
            name="uq_daily_nutrition_user_date",
        ),
        db.UniqueConstraint(
            "source_file_id",
            name="uq_daily_nutrition_source_file",
        ),
        db.Index("ix_daily_nutrition_user_date", "user_id", "date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    date = db.Column(db.Date, nullable=False)
    source = db.Column(db.String(32), nullable=False)
    source_file_id = db.Column(
        db.Integer,
        db.ForeignKey("uploaded_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes = db.Column(db.Text, nullable=True)
    calories = db.Column(db.Numeric(12, 3), nullable=True)
    protein_g = db.Column(db.Numeric(12, 3), nullable=True)
    fat_g = db.Column(db.Numeric(12, 3), nullable=True)
    net_carbs_g = db.Column(db.Numeric(12, 3), nullable=True)
    total_carbs_g = db.Column(db.Numeric(12, 3), nullable=True)
    fiber_g = db.Column(db.Numeric(12, 3), nullable=True)
    sugar_g = db.Column(db.Numeric(12, 3), nullable=True)
    sodium_mg = db.Column(db.Numeric(12, 3), nullable=True)
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

    user = db.relationship("User", back_populates="daily_nutrition_records")
    source_file = db.relationship("UploadedFile")
    meals = db.relationship(
        "NutritionMeal",
        back_populates="daily_nutrition",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="NutritionMeal.sort_order",
    )


class NutritionMeal(db.Model):
    __tablename__ = "nutrition_meals"
    __table_args__ = (
        db.CheckConstraint("sort_order >= 1", name="ck_nutrition_meals_sort_order"),
        db.UniqueConstraint(
            "daily_nutrition_id",
            "sort_order",
            name="uq_nutrition_meals_day_order",
        ),
        db.Index(
            "ix_nutrition_meals_user_day",
            "user_id",
            "daily_nutrition_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    daily_nutrition_id = db.Column(
        db.Integer,
        db.ForeignKey("daily_nutrition.id", ondelete="CASCADE"),
        nullable=False,
    )
    meal_type = db.Column(db.String(32), nullable=False)
    name = db.Column(db.String(200), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False)

    daily_nutrition = db.relationship("DailyNutrition", back_populates="meals")
    items = db.relationship(
        "NutritionItem",
        back_populates="meal",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="NutritionItem.sort_order",
    )


class NutritionItem(db.Model):
    __tablename__ = "nutrition_items"
    __table_args__ = (
        *_metric_constraints("nutrition_items"),
        db.CheckConstraint(
            "quantity IS NULL OR quantity >= 0",
            name="ck_nutrition_items_quantity",
        ),
        db.CheckConstraint("sort_order >= 1", name="ck_nutrition_items_sort_order"),
        db.UniqueConstraint(
            "nutrition_meal_id",
            "sort_order",
            name="uq_nutrition_items_meal_order",
        ),
        db.Index(
            "ix_nutrition_items_user_meal",
            "user_id",
            "nutrition_meal_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    nutrition_meal_id = db.Column(
        db.Integer,
        db.ForeignKey("nutrition_meals.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Numeric(12, 3), nullable=True)
    unit = db.Column(db.String(32), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False)
    calories = db.Column(db.Numeric(12, 3), nullable=True)
    protein_g = db.Column(db.Numeric(12, 3), nullable=True)
    fat_g = db.Column(db.Numeric(12, 3), nullable=True)
    net_carbs_g = db.Column(db.Numeric(12, 3), nullable=True)
    total_carbs_g = db.Column(db.Numeric(12, 3), nullable=True)
    fiber_g = db.Column(db.Numeric(12, 3), nullable=True)
    sugar_g = db.Column(db.Numeric(12, 3), nullable=True)
    sodium_mg = db.Column(db.Numeric(12, 3), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    meal = db.relationship("NutritionMeal", back_populates="items")
    food_product_id = db.Column(
        db.Integer,
        db.ForeignKey("food_products.id", ondelete="SET NULL"),
        nullable=True,
    )
    food_product = db.relationship("FoodProduct")


FOOD_PRODUCT_METRICS = (
    "calories_per_100g",
    "protein_g_per_100g",
    "fat_g_per_100g",
    "carbs_g_per_100g",
    "net_carbs_g_per_100g",
    "fiber_g_per_100g",
    "sodium_mg_per_100g",
)


class FoodProduct(db.Model):
    """User-owned reusable food/product record with macros per 100 g."""

    __tablename__ = "food_products"
    __table_args__ = (
        *tuple(
            db.CheckConstraint(
                f"{field} IS NULL OR {field} >= 0",
                name=f"ck_food_products_{field}",
            )
            for field in FOOD_PRODUCT_METRICS
        ),
        db.UniqueConstraint(
            "user_id",
            "name",
            "brand",
            name="uq_food_product_user_name_brand",
        ),
        db.Index("ix_food_products_user_active", "user_id", "is_active"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = db.Column(db.String(200), nullable=False)
    brand = db.Column(db.String(200), nullable=True)
    serving_size_g = db.Column(db.Numeric(10, 3), nullable=True)
    serving_label = db.Column(db.String(64), nullable=True)
    calories_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    protein_g_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    fat_g_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    carbs_g_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    net_carbs_g_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    fiber_g_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    sodium_mg_per_100g = db.Column(db.Numeric(10, 3), nullable=True)
    source = db.Column(db.String(32), nullable=False)
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

    user = db.relationship("User", back_populates="food_products")
