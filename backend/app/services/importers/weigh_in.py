from datetime import datetime
from decimal import Decimal

from app.extensions import db
from app.models import UploadedFile, WeighIn
from app.services.importers.base import ImporterError, load_json_source
from app.services.validation import validate_json_document


class WeighInImportError(ValueError):
    pass


def _existing_record(source_file_id: int, user_id: int) -> WeighIn | None:
    return db.session.execute(
        db.select(WeighIn).where(
            WeighIn.source_file_id == source_file_id,
            WeighIn.user_id == user_id,
        )
    ).scalar_one_or_none()


def _decimal(data: dict, field: str) -> Decimal | None:
    value = data.get(field)
    return Decimal(str(value)) if value is not None else None


def import_weigh_in_file(
    source_file: UploadedFile,
    user_id: int,
) -> tuple[WeighIn, bool]:
    if source_file.user_id != user_id:
        raise WeighInImportError("Weigh-in file does not belong to this user")
    existing = _existing_record(source_file.id, user_id)
    if existing is not None:
        return existing, True
    if source_file.source_type not in {"uploaded", "manual_generated"}:
        raise WeighInImportError("Unsupported weigh-in source file type")

    try:
        document = load_json_source(source_file, user_id)
    except ImporterError as error:
        raise WeighInImportError(str(error)) from error
    validate_json_document(document, "weigh_in")
    if document["user_id"] != user_id:
        raise WeighInImportError("Weigh-in document does not belong to this user")
    if document["source_type"] != source_file.source_type:
        raise WeighInImportError("Weigh-in source type does not match its file")

    data = document["data"]
    recorded_at = datetime.fromisoformat(data["recorded_at"].replace("Z", "+00:00"))
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise WeighInImportError("Weigh-in recorded_at must include a timezone")
    source = data.get("source", document["source_type"]).strip()
    if not source:
        raise WeighInImportError("Weigh-in source must not be blank")

    same_time = db.session.execute(
        db.select(WeighIn).where(
            WeighIn.user_id == user_id,
            WeighIn.recorded_at == recorded_at,
        )
    ).scalar_one_or_none()
    if same_time is not None:
        if same_time.source == source:
            return same_time, True
        raise WeighInImportError(
            "A weigh-in from another source already exists at this time"
        )

    record = WeighIn(
        user_id=user_id,
        recorded_at=recorded_at,
        weight_kg=_decimal(data, "weight_kg"),
        body_fat_percentage=_decimal(data, "body_fat_percent"),
        muscle_mass_kg=_decimal(data, "muscle_mass_kg"),
        water_percentage=_decimal(data, "water_percent"),
        visceral_fat=_decimal(data, "visceral_fat"),
        bmr_kcal=_decimal(data, "bmr_kcal"),
        bmi=_decimal(data, "bmi"),
        source=source,
        source_file_id=source_file.id,
        raw_payload_json=document,
        notes=data.get("notes"),
    )
    db.session.add(record)
    db.session.commit()
    return record, False
