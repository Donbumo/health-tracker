"""Tests for the FoodProduct model — Phase 1.

Covers: create (minimal + all fields), user isolation, unique constraint.
"""

import pytest
from decimal import Decimal
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import FoodProduct, User


def _make_user(username: str) -> User:
    user = User(username=username, role="user")
    user.set_password("test-password")
    db.session.add(user)
    db.session.flush()
    return user


def _make_product(user_id: int, name: str = "Demo Product", **kwargs) -> FoodProduct:
    product = FoodProduct(
        user_id=user_id,
        name=name,
        source="manual",
        **kwargs,
    )
    db.session.add(product)
    db.session.flush()
    return product


def test_create_food_product_minimal(app, user):
    """Creating a product with only required fields succeeds."""
    with app.app_context():
        product = _make_product(user, "Chicken Breast")
        db.session.commit()
        saved = db.session.get(FoodProduct, product.id)
        assert saved is not None
        assert saved.name == "Chicken Breast"
        assert saved.source == "manual"
        assert saved.user_id == user
        assert saved.is_active is True
        # All optional macro fields should be None
        assert saved.calories_per_100g is None
        assert saved.protein_g_per_100g is None
        assert saved.fat_g_per_100g is None
        assert saved.brand is None
        assert saved.serving_size_g is None


def test_create_food_product_all_fields(app, user):
    """Creating a product with all optional fields populates them correctly."""
    with app.app_context():
        product = _make_product(
            user,
            "Greek Yogurt",
            brand="FictionalBrand",
            serving_size_g=Decimal("170.000"),
            serving_label="170 g container",
            calories_per_100g=Decimal("59.000"),
            protein_g_per_100g=Decimal("10.000"),
            fat_g_per_100g=Decimal("0.700"),
            carbs_g_per_100g=Decimal("3.600"),
            net_carbs_g_per_100g=Decimal("3.600"),
            fiber_g_per_100g=Decimal("0.000"),
            sodium_mg_per_100g=Decimal("36.000"),
            notes="Fictional product for tests only.",
            is_active=True,
        )
        db.session.commit()
        saved = db.session.get(FoodProduct, product.id)
        assert saved.brand == "FictionalBrand"
        assert saved.serving_size_g == Decimal("170.000")
        assert saved.calories_per_100g == Decimal("59.000")
        assert saved.protein_g_per_100g == Decimal("10.000")
        assert saved.sodium_mg_per_100g == Decimal("36.000")
        assert saved.notes == "Fictional product for tests only."


def test_food_product_isolated_by_user(app, user):
    """A user cannot see another user's food products."""
    with app.app_context():
        product = _make_product(user, "Isolated Product")
        product_id = product.id
        second = _make_user("second-food-user")
        second_id = second.id
        db.session.commit()

    with app.app_context():
        # Direct query filtered by second user should return nothing.
        result = db.session.execute(
            db.select(FoodProduct).where(
                FoodProduct.id == product_id,
                FoodProduct.user_id == second_id,
            )
        ).scalar_one_or_none()
        assert result is None

        # Query for the correct user works.
        result = db.session.execute(
            db.select(FoodProduct).where(
                FoodProduct.id == product_id,
                FoodProduct.user_id == user,
            )
        ).scalar_one_or_none()
        assert result is not None


def test_food_product_unique_constraint_same_user(app, user):
    """Two products with same name + brand under the same user raise IntegrityError."""
    with app.app_context():
        _make_product(user, "Oat Milk", brand="FictionalBrand")
        db.session.flush()
        with pytest.raises(IntegrityError):
            _make_product(user, "Oat Milk", brand="FictionalBrand")
            db.session.flush()


def test_food_product_same_name_different_user_is_allowed(app, user):
    """Same name + brand is allowed for different users."""
    with app.app_context():
        second = _make_user("third-food-user")
        _make_product(user, "Shared Name", brand="BrandX")
        _make_product(second.id, "Shared Name", brand="BrandX")
        db.session.commit()
        count = db.session.execute(
            db.select(db.func.count(FoodProduct.id))
        ).scalar_one()
        assert count == 2


def test_food_product_timestamps_are_set(app, user):
    """created_at and updated_at are set on creation."""
    with app.app_context():
        product = _make_product(user, "Timestamped Product")
        db.session.commit()
        saved = db.session.get(FoodProduct, product.id)
        assert saved.created_at is not None
        assert saved.updated_at is not None
