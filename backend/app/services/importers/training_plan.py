import hashlib

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import TrainingPlan, TrainingPlanVersion, UploadedFile
from app.services.importers.base import ImporterError, load_json_source
from app.services.training_plans import (
    TrainingPlanImportError,
    _validate_plan_ordering,
    serialize_training_plan,
)
from app.services.validation import validate_json_document


def _existing_plan(source_file_id: int, user_id: int) -> TrainingPlan | None:
    version = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.source_file_id == source_file_id,
            TrainingPlanVersion.user_id == user_id,
        )
    ).scalar_one_or_none()
    return version.training_plan if version else None


def load_training_plan_document(
    source_file: UploadedFile,
    user_id: int,
) -> dict:
    if source_file.user_id != user_id:
        raise TrainingPlanImportError("Source file does not belong to this user")
    if source_file.source_type != "uploaded":
        raise TrainingPlanImportError("Training plans must originate from an upload")

    try:
        document = load_json_source(source_file, user_id)
    except ImporterError as error:
        raise TrainingPlanImportError(str(error)) from error

    validate_json_document(document, "training_plan")
    if document["user_id"] != user_id:
        raise TrainingPlanImportError("Document user_id does not match its owner")
    if document["source_type"] != "uploaded":
        raise TrainingPlanImportError("Imported plans require uploaded source_type")
    _validate_plan_ordering(document)

    name = document["data"]["name"].strip()
    if not name:
        raise TrainingPlanImportError("Training plan name must not be blank")
    return document


def import_training_plan_file(
    source_file: UploadedFile,
    user_id: int,
) -> tuple[TrainingPlan, bool]:
    existing = _existing_plan(source_file.id, user_id)
    if existing:
        return existing, True

    document = load_training_plan_document(source_file, user_id)
    name = document["data"]["name"].strip()
    description = document["data"].get("description")
    if description is not None:
        description = description.strip() or None

    canonical_bytes = serialize_training_plan(document)
    content_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    plan = TrainingPlan(
        user_id=user_id,
        name=name,
        description=description,
        active_version_number=1,
    )
    db.session.add(plan)

    try:
        db.session.flush()
        version = TrainingPlanVersion(
            user_id=user_id,
            training_plan_id=plan.id,
            version_number=1,
            source_file_id=source_file.id,
            created_by_user_id=user_id,
            change_reason="Initial import",
            schema_version=document["schema_version"],
            sha256=content_sha256,
            content=document,
        )
        db.session.add(version)
        db.session.commit()
        return plan, False
    except IntegrityError:
        db.session.rollback()
        existing = _existing_plan(source_file.id, user_id)
        if existing:
            return existing, True
        raise


# Compatibility alias for callers that use the original function name.
import_training_plan = import_training_plan_file
