import hashlib
import json
import math
import os
import uuid
from datetime import datetime
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
