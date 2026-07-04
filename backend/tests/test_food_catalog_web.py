"""Tests for the FoodProduct web views — Phase 3."""

import io
import json

from app.extensions import db
from app.models import FoodProduct, User
from tests.conftest import login


def _make_user(username: str) -> User:
    user = User(username=username, role="user")
    user.set_password("test-password")
    db.session.add(user)
    db.session.flush()
    return user


def test_food_list_empty_state(client, user):
    login(client)
    response = client.get("/foods")
    assert response.status_code == 200
    assert b"No tienes productos registrados" in response.data


def test_food_list_shows_products(app, client, user):
    login(client)
    with app.app_context():
        product = FoodProduct(
            user_id=user,
            name="List Test Product",
            brand="BrandX",
            source="manual",
        )
        db.session.add(product)
        db.session.commit()

    response = client.get("/foods")
    assert response.status_code == 200
    assert b"List Test Product" in response.data
    assert b"BrandX" in response.data


def test_food_create_manual(app, client, user):
    login(client)
    response = client.post(
        "/foods/new",
        data={
            "name": "New Manual Product",
            "brand": "NewBrand",
            "calories_per_100g": "150.5",
            "protein_g_per_100g": "20.2",
            "is_active": "y",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Producto guardado correctamente" in response.data

    with app.app_context():
        product = db.session.execute(
            db.select(FoodProduct).where(FoodProduct.name == "New Manual Product")
        ).scalar_one()
        assert product.brand == "NewBrand"
        assert product.user_id == user


def test_food_detail_isolates_user(app, client, user):
    login(client)
    with app.app_context():
        second = _make_user("second")
        db.session.commit()
        second_id = second.id

        product = FoodProduct(
            user_id=second_id,
            name="Other User Product",
            source="manual",
        )
        db.session.add(product)
        db.session.commit()
        product_id = product.id

    # Current user trying to access other user's product
    response = client.get(f"/foods/{product_id}")
    assert response.status_code == 404


def test_food_edit(app, client, user):
    login(client)
    with app.app_context():
        product = FoodProduct(
            user_id=user,
            name="Old Name",
            source="manual",
        )
        db.session.add(product)
        db.session.commit()
        product_id = product.id

    response = client.post(
        f"/foods/{product_id}/edit",
        data={
            "name": "Updated Name",
            "calories_per_100g": "99.9",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Producto actualizado" in response.data

    with app.app_context():
        updated = db.session.get(FoodProduct, product_id)
        assert updated.name == "Updated Name"


def test_food_import_json(app, client, user):
    login(client)
    document = {
        "schema_version": "1.0",
        "type": "food_product",
        "user_id": user,
        "source_type": "uploaded",
        "data": {
            "name": "JSON Imported Product",
            "source": "manual",
            "calories_per_100g": 123.4,
        }
    }
    response = client.post(
        "/foods/import",
        data={"file": (io.BytesIO(json.dumps(document).encode("utf-8")), "food.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Producto importado" in response.data

    with app.app_context():
        product = db.session.execute(
            db.select(FoodProduct).where(FoodProduct.name == "JSON Imported Product")
        ).scalar_one()
        assert product.user_id == user


def test_food_import_invalid(client, user):
    login(client)
    document = {
        "schema_version": "1.0",
        "type": "food_product",
        "user_id": user,
        "source_type": "uploaded",
        "data": {
            # Missing name
            "source": "manual",
        }
    }
    response = client.post(
        "/foods/import",
        data={"file": (io.BytesIO(json.dumps(document).encode("utf-8")), "food.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Error al importar" in response.data
