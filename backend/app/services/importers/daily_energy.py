from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import DailyEnergy, UploadedFile
from app.services.importers.base import ImporterError, load_json_source
from app.services.validation import validate_json_document


class DailyEnergyImportError(ValueError):
    pass


def _existing_record(source_file_id: int, user_id: int) -> DailyEnergy | None:
    return db.session.execute(
        db.select(DailyEnergy).where(
            DailyEnergy.source_file_id == source_file_id,
            DailyEnergy.user_id == user_id,
        )
    ).scalar_one_or_none()


def import_daily_energy_file(
    source_file: UploadedFile,
    user_id: int,
) -> tuple[DailyEnergy, bool]:
    if source_file.user_id != user_id:
        raise DailyEnergyImportError("Daily energy file does not belong to this user")
    existing = _existing_record(source_file.id, user_id)
    if existing is not None:
        return existing, True
    if source_file.source_type not in {"uploaded", "manual_generated"}:
        raise DailyEnergyImportError("Unsupported daily energy source file type")

    try:
        document = load_json_source(source_file, user_id)
    except ImporterError as error:
        raise DailyEnergyImportError(str(error)) from error
    validate_json_document(document, "daily_energy")
    if document["user_id"] != user_id:
        raise DailyEnergyImportError("Daily energy document does not belong to this user")
    if document["source_type"] != source_file.source_type:
        raise DailyEnergyImportError("Daily energy source type does not match its file")

    data = document["data"]
    record_date = date.fromisoformat(data["date"])
    source = data.get("source", document["source_type"]).strip()
    if not source:
        raise DailyEnergyImportError("Daily energy source must not be blank")
    same_date = db.session.execute(
        db.select(DailyEnergy).where(
            DailyEnergy.user_id == user_id,
            DailyEnergy.date == record_date,
        )
    ).scalar_one_or_none()
    if same_date is not None:
        raise DailyEnergyImportError("Daily energy already exists for this date")

    def decimal_value(field: str) -> Decimal | None:
        value = data.get(field)
        return Decimal(str(value)) if value is not None else None

    record = DailyEnergy(
        user_id=user_id,
        date=record_date,
        total_calories=decimal_value("total_expenditure_kcal"),
        active_calories=decimal_value("active_expenditure_kcal"),
        resting_calories=decimal_value("resting_expenditure_kcal"),
        steps=data.get("steps"),
        distance_meters=decimal_value("distance_meters"),
        source=source,
        source_file_id=source_file.id,
        notes=data.get("notes"),
        raw_payload_json=document,
    )
    db.session.add(record)
    db.session.commit()
    return record, False
