from app.extensions import db
from app.models import DailyEnergy, UploadedFile
from app.services.importers.base import ImporterError, load_json_source
from app.services.validation import validate_json_document
from app.services.energy_days import upsert_document, EnergyConflict


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
    if document["source_type"] != source_file.source_type and document['schema_version'] != '1.1':
        raise DailyEnergyImportError("Daily energy source type does not match its file")

    try:
        record = upsert_document(document, user_id, source_file=source_file)
        duplicate = record._energy_replay
        db.session.commit()
        return record, duplicate
    except EnergyConflict as error:
        db.session.rollback()
        raise DailyEnergyImportError(str(error)) from error
