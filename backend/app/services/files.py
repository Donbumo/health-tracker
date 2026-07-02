import hashlib
import os
import uuid
from pathlib import Path

from flask import current_app
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import UploadedFile


class UploadError(ValueError):
    pass


def _original_filename(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(character for character in name if character.isprintable())
    name = name.strip()
    if not name:
        raise UploadError("Selecciona un archivo con un nombre válido.")
    return name[:255]


def store_uploaded_file(file: FileStorage, user_id: int) -> tuple[UploadedFile, bool]:
    """Persist an upload and return (database record, was_duplicate)."""
    original_filename = _original_filename(file.filename)
    upload_root = Path(current_app.config["UPLOAD_ROOT"])
    user_directory = upload_root / f"user_{user_id}"
    user_directory.mkdir(parents=True, exist_ok=True)

    temporary_path = user_directory / f".{uuid.uuid4().hex}.uploading"
    digest = hashlib.sha256()
    size_bytes = 0

    try:
        with temporary_path.open("xb") as destination:
            while chunk := file.stream.read(1024 * 1024):
                destination.write(chunk)
                digest.update(chunk)
                size_bytes += len(chunk)

        sha256 = digest.hexdigest()
        existing = db.session.execute(
            db.select(UploadedFile).where(
                UploadedFile.user_id == user_id,
                UploadedFile.sha256 == sha256,
            )
        ).scalar_one_or_none()
        if existing:
            temporary_path.unlink(missing_ok=True)
            return existing, True

        stored_filename = sha256
        final_path = user_directory / stored_filename
        os.replace(temporary_path, final_path)

        storage_path = (
            Path("uploads") / "raw" / f"user_{user_id}" / stored_filename
        ).as_posix()
        record = UploadedFile(
            user_id=user_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            storage_path=storage_path,
            sha256=sha256,
            size_bytes=size_bytes,
            mime_type=(file.mimetype or None),
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
                UploadedFile.sha256 == digest.hexdigest(),
            )
        ).scalar_one_or_none()
        if existing:
            return existing, True
        raise
    except Exception:
        db.session.rollback()
        temporary_path.unlink(missing_ok=True)
        raise
