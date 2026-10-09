"""Additive local catalog and consumed events; templates remain Recipe."""
from datetime import datetime, timezone
from uuid import uuid4
from app.extensions import db


def uid():
    return str(uuid4())


class FoodCatalogSource(db.Model):
    __tablename__ = "food_catalog_sources"
    id = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    license = db.Column(db.String(200), nullable=False)
    active_revision = db.Column(db.String(64))
    previous_revision = db.Column(db.String(64))
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")


class FoodCatalogRevision(db.Model):
    __tablename__ = "food_catalog_revisions"
    __table_args__ = (db.UniqueConstraint("source_id", "revision", name="uq_food_catalog_revision"),)
    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.String(64), db.ForeignKey("food_catalog_sources.id"), nullable=False)
    revision = db.Column(db.String(64), nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    manifest_json = db.Column(db.JSON, nullable=False)
    state = db.Column(db.String(16), nullable=False, default="staged")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class CatalogFood(db.Model):
    __tablename__ = "catalog_foods"
    __table_args__ = (
        db.UniqueConstraint("catalog_revision_id", "source_food_id", name="uq_catalog_food_identity"),
        db.Index("ix_catalog_food_search", "catalog_revision_id", "name"),)
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, unique=True, default=uid)
    catalog_revision_id = db.Column(db.Integer, db.ForeignKey("food_catalog_revisions.id"), nullable=False)
    catalog_revision = db.relationship("FoodCatalogRevision", lazy="joined")
    source_food_id = db.Column(db.String(64), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    preparation = db.Column(db.String(200), nullable=False)
    snapshot_json = db.Column(db.JSON, nullable=False)


class Nutrient(db.Model):
    __tablename__ = "nutrients"
    id = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    unit = db.Column(db.String(16), nullable=False)
    group = db.Column(db.String(16), nullable=False)


class FoodNutrient(db.Model):
    __tablename__ = "food_nutrients"
    __table_args__ = (
        db.UniqueConstraint("food_id", "nutrient_id", name="uq_food_nutrient"),
        db.CheckConstraint("value IS NULL OR value >= 0", name="ck_food_nutrient_nonnegative"),
        db.CheckConstraint("state IN ('known','unknown','trace','below_limit')", name="ck_food_nutrient_state"),)
    id = db.Column(db.Integer, primary_key=True)
    food_id = db.Column(db.Integer, db.ForeignKey("catalog_foods.id"), nullable=False)
    nutrient_id = db.Column(db.String(64), db.ForeignKey("nutrients.id"), nullable=False)
    value = db.Column(db.Numeric(30, 12))
    state = db.Column(db.String(16), nullable=False)
    provenance_json = db.Column(db.JSON, nullable=False)


class FoodServing(db.Model):
    __tablename__ = "food_servings"
    __table_args__ = (
        db.UniqueConstraint("food_id", "source_serving_id", name="uq_food_serving"),
        db.CheckConstraint("amount > 0", name="ck_food_serving_positive"),)
    id = db.Column(db.Integer, primary_key=True)
    food_id = db.Column(db.Integer, db.ForeignKey("catalog_foods.id"), nullable=False)
    source_serving_id = db.Column(db.String(64), nullable=False)
    label = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Numeric(30, 12), nullable=False)
    unit = db.Column(db.String(8), nullable=False)


class MealDraft(db.Model):
    __tablename__ = "meal_drafts"
    __table_args__ = (db.Index("ix_meal_draft_owner", "user_id", "state"),)
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, unique=True, default=uid)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    state = db.Column(db.String(16), nullable=False, default="pending", server_default="pending")
    snapshot_json = db.Column(db.JSON, nullable=False)
    accepted_json = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class MealLog(db.Model):
    __tablename__ = "meal_logs"
    __table_args__ = (
        db.UniqueConstraint("user_id", "client_event_id", name="uq_meal_log_event"),
        db.Index("ix_meal_log_owner_date", "user_id", "local_date"),)
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, unique=True, default=uid)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    client_event_id = db.Column(db.String(36), nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    local_date = db.Column(db.Date, nullable=False)
    consumed_at = db.Column(db.DateTime(timezone=True))
    timezone = db.Column(db.String(64), nullable=False)
    projection_item_id = db.Column(db.Integer, db.ForeignKey("nutrition_items.id", ondelete="RESTRICT"), nullable=False, unique=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipes.id", ondelete="SET NULL"))
    snapshot_json = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
