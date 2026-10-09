"""Owner-private temporary originals, promoted only after signed confirmation."""
import hashlib
import io
import time
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.services.gym_programs import GymError


def _directory(user_id):
    root = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    directory = root / f"user_{user_id}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def stage_source(draft, content, filename, user_id):
    directory = _directory(user_id)
    files = list(directory.glob('.gym-preview-*.tmp'))
    for path in files:
        if path.stat().st_mtime < time.time() - 3600:
            path.unlink(missing_ok=True)
    if len(list(directory.glob('.gym-preview-*.tmp'))) >= 20:
        raise GymError("Hay demasiados previews pendientes; espera a que expiren.")
    draft.source_ref = str(uuid.uuid4())
    draft.source_filename = str(filename).replace('\\', '/').rsplit('/', 1)[-1][:200]
    draft.source_sha256 = hashlib.sha256(content).hexdigest()
    (directory / f'.gym-preview-{draft.source_ref}.tmp').write_bytes(content)


def promote_source(draft, user_id):
    if not draft.source_ref:
        return None
    try:
        reference = str(uuid.UUID(draft.source_ref))
    except (ValueError, TypeError) as error:
        raise GymError("Original inválido; vuelve a cargarlo.") from error
    path = _directory(user_id) / f'.gym-preview-{reference}.tmp'
    if not path.is_file() or path.stat().st_mtime < time.time() - 3600:
        # A confirmed retry can reuse the promoted original by owner + digest.
        from app.extensions import db
        from app.models import UploadedFile
        row = db.session.execute(db.select(UploadedFile).where(UploadedFile.user_id == user_id, UploadedFile.sha256 == draft.source_sha256)).scalar_one_or_none()
        if row is not None:
            return row
        raise GymError("El original expiró; vuelve a cargarlo.")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != draft.source_sha256:
        raise GymError("El original cambió; vuelve a cargarlo.")
    from app.services.files import store_uploaded_file
    source, _ = store_uploaded_file(FileStorage(stream=io.BytesIO(content), filename=draft.source_filename), user_id)
    path.unlink(missing_ok=True)
    return source
