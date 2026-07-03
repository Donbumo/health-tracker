import hashlib
import json
import math
import os
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from flask import current_app
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import UploadedFile
from app.services.validation import validate_json_document


class ManualJsonGenerationError(ValueError):
    pass


def _finite_number(value: Decimal | float | int) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ManualJsonGenerationError("Numeric values must be finite")
    return number


def build_weigh_in_document(
    *,
    user_id: int,
    recorded_at: datetime,
    weight_kg: Decimal | float,
    body_fat_percent: Decimal | float | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ManualJsonGenerationError("recorded_at must include a timezone")

    data: dict[str, Any] = {
        "recorded_at": recorded_at.isoformat(timespec="seconds"),
        "weight_kg": _finite_number(weight_kg),
    }
    if body_fat_percent is not None:
        data["body_fat_percent"] = _finite_number(body_fat_percent)
    if notes and notes.strip():
        data["notes"] = notes.strip()

    return {
        "schema_version": "1.0",
        "record_type": "weigh_in",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": data,
    }


def build_daily_energy_document(
    *,
    user_id: int,
    record_date: date,
    total_calories: Decimal | float | int | None = None,
    active_calories: Decimal | float | int | None = None,
    resting_calories: Decimal | float | int | None = None,
    steps: int | None = None,
    distance_meters: Decimal | float | int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"date": record_date.isoformat(), "source": "manual"}
    optional_numbers = {
        "total_expenditure_kcal": total_calories,
        "active_expenditure_kcal": active_calories,
        "resting_expenditure_kcal": resting_calories,
        "distance_meters": distance_meters,
    }
    for field, value in optional_numbers.items():
        if value is not None:
            data[field] = _finite_number(value)
    if steps is not None:
        data["steps"] = steps
    if notes and notes.strip():
        data["notes"] = notes.strip()
    return {
        "schema_version": "1.0",
        "record_type": "daily_energy",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": data,
    }


def build_daily_nutrition_document(
    *,
    user_id: int,
    record_date: date,
    meal_type: str,
    meal_name: str | None,
    item_name: str,
    quantity: Decimal | float | int | None = None,
    unit: str | None = None,
    calories: Decimal | float | int | None = None,
    protein_g: Decimal | float | int | None = None,
    fat_g: Decimal | float | int | None = None,
    net_carbs_g: Decimal | float | int | None = None,
    total_carbs_g: Decimal | float | int | None = None,
    fiber_g: Decimal | float | int | None = None,
    sugar_g: Decimal | float | int | None = None,
    sodium_mg: Decimal | float | int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {"name": item_name.strip()}
    if not item["name"]:
        raise ManualJsonGenerationError("Nutrition item name must not be blank")
    if quantity is not None:
        item["quantity"] = _finite_number(quantity)
    if unit and unit.strip():
        item["unit"] = unit.strip()
    for field, value in {
        "calories_kcal": calories,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "net_carbs_g": net_carbs_g,
        "total_carbs_g": total_carbs_g,
        "fiber_g": fiber_g,
        "sugar_g": sugar_g,
        "sodium_mg": sodium_mg,
    }.items():
        if value is not None:
            item[field] = _finite_number(value)

    meal: dict[str, Any] = {"meal_type": meal_type, "items": [item]}
    if meal_name and meal_name.strip():
        meal["name"] = meal_name.strip()
    data: dict[str, Any] = {
        "date": record_date.isoformat(),
        "source": "manual",
        "meals": [meal],
    }
    if notes and notes.strip():
        data["notes"] = notes.strip()
    return {
        "schema_version": "1.0",
        "record_type": "daily_nutrition",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": data,
    }


def generate_standard_json(
    *,
    document: dict[str, Any],
    schema_name: str,
    user_id: int,
    original_filename: str,
) -> tuple[UploadedFile, bool]:
    """Validate, serialize and persist a standard manual JSON document."""
    if document.get("user_id") != user_id:
        raise ManualJsonGenerationError("Document user_id does not match its owner")
    if document.get("source_type") != "manual_generated":
        raise ManualJsonGenerationError("Manual documents require manual_generated source_type")

    validate_json_document(document, schema_name)
    serialized = (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    sha256 = hashlib.sha256(serialized).hexdigest()

    existing = db.session.execute(
        db.select(UploadedFile).where(
            UploadedFile.user_id == user_id,
            UploadedFile.sha256 == sha256,
        )
    ).scalar_one_or_none()
    if existing:
        return existing, True

    safe_original_filename = secure_filename(original_filename)
    if not safe_original_filename:
        raise ManualJsonGenerationError("A valid original filename is required")
    if not safe_original_filename.endswith(".json"):
        safe_original_filename += ".json"

    generated_root = Path(current_app.config["GENERATED_UPLOAD_ROOT"])
    user_directory = generated_root / f"user_{user_id}"
    user_directory.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{sha256}.json"
    final_path = user_directory / stored_filename
    temporary_path = user_directory / f".{uuid.uuid4().hex}.generating"

    try:
        with temporary_path.open("xb") as generated_file:
            generated_file.write(serialized)
        os.replace(temporary_path, final_path)

        storage_path = (
            Path("uploads") / "generated" / f"user_{user_id}" / stored_filename
        ).as_posix()
        record = UploadedFile(
            user_id=user_id,
            original_filename=safe_original_filename[:255],
            stored_filename=stored_filename,
            storage_path=storage_path,
            source_type="manual_generated",
            detected_type=schema_name,
            import_status="imported",
            sha256=sha256,
            size_bytes=len(serialized),
            mime_type="application/json",
        )
        db.session.add(record)
        db.session.commit()
        return record, False
    except IntegrityError:
        db.session.rollback()
        temporary_path.unlink(missing_ok=True)
        existing = db.session.execute(
            db.select(UploadedFile).where(
                UploadedFile.user_id == user_id,
                UploadedFile.sha256 == sha256,
            )
        ).scalar_one_or_none()
        if existing:
            return existing, True
        raise
    except Exception:
        db.session.rollback()
        temporary_path.unlink(missing_ok=True)
        raise
