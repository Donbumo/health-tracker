"""Tests for the FoodProduct importer — Phase 2."""

import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app.extensions import db
from app.models import FoodProduct, UploadedFile, User
from app.services.importers.food_product import (
    FoodProductImportError,
    import_food_product_file,
)
from app.services.validation import JsonSchemaValidationError


def _make_user(username: str) -> User:
    user = User(username=username, role="user")
    user.set_password("test-password")
    db.session.add(user)
    db.session.flush()
    return user


def _create_mock_source_file(app, user_id: int, document: dict) -> UploadedFile:
    filename = "mock_food.json"
    upload_root = Path(app.config["UPLOAD_ROOT"])
    storage_path = upload_root / filename
    storage_path.write_text(json.dumps(document), encoding="utf-8")
    
    file_record = UploadedFile(
        user_id=user_id,
        original_filename=filename,
        stored_filename=filename,
        storage_path=f"uploads/raw/{filename}",
        source_type=document["source_type"],
        detected_type="food_product",
        size_bytes=storage_path.stat().st_size,
        mime_type="application/json",
        sha256=f"mockhash_{uuid.uuid4().hex}",
        import_status="pending",
    )
    db.session.add(file_record)
    db.session.commit()
    return file_record


def _document(user_id: int, **overrides) -> dict:
    doc = {
        "schema_version": "1.0",
        "type": "food_product",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "name": "Test Product",
            "brand": "Test Brand",
            "source": "manual",
            "calories_per_100g": 100,
            "protein_g_per_100g": 10.5,
        }
    }
    doc["data"].update(overrides)
    return doc


def test_import_valid_food_product(app, user):
    """Importing a valid food product document creates a FoodProduct record."""
    with app.app_context():
        document = _document(user)
        source_file = _create_mock_source_file(app, user, document)
        product, duplicate = import_food_product_file(source_file, user)
        assert duplicate is False
        assert product.name == "Test Product"
        assert product.brand == "Test Brand"
        assert product.calories_per_100g == Decimal("100.000")
        assert product.protein_g_per_100g == Decimal("10.500")


def test_import_duplicate_deduplicates(app, user):
    """Importing the same name and brand for the same user returns the existing product."""
    with app.app_context():
        document = _document(user)
        source_file1 = _create_mock_source_file(app, user, document)
        product1, duplicate1 = import_food_product_file(source_file1, user)
        assert duplicate1 is False

        source_file2 = _create_mock_source_file(app, user, document)
        product2, duplicate2 = import_food_product_file(source_file2, user)
        assert duplicate2 is True
        assert product1.id == product2.id


def test_import_invalid_schema(app, user):
    """Missing required schema fields raises JsonSchemaValidationError."""
    with app.app_context():
        document = _document(user)
        del document["data"]["name"]
        source_file = _create_mock_source_file(app, user, document)
        with pytest.raises(JsonSchemaValidationError):
            import_food_product_file(source_file, user)


def test_import_isolation_prevents_cross_user(app, user):
    """A user cannot import a file belonging to another user."""
    with app.app_context():
        second = _make_user("second")
        db.session.commit()
        second_id = second.id

        document = _document(second_id)
        # Source file belongs to second_id
        source_file = _create_mock_source_file(app, second_id, document)
        
        # Current user tries to import it
        with pytest.raises(FoodProductImportError) as exc:
            import_food_product_file(source_file, user)
        assert "does not belong to this user" in str(exc.value)


def test_import_document_user_mismatch(app, user):
    """Document's user_id must match the caller."""
    with app.app_context():
        second = _make_user("second")
        db.session.commit()
        
        document = _document(second.id)
        # Source file belongs to current user, but inner document claims second user
        source_file = _create_mock_source_file(app, user, document)
        
        with pytest.raises(FoodProductImportError) as exc:
            import_food_product_file(source_file, user)
        assert "document does not belong to this user" in str(exc.value)
