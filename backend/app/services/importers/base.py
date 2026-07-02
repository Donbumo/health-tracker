import json
from pathlib import Path
from typing import Any

from flask import current_app

from app.models import UploadedFile


class ImporterError(ValueError):
    pass


def source_file_path(source_file: UploadedFile, user_id: int) -> Path:
    if source_file.user_id != user_id:
        raise ImporterError("Source file does not belong to this user")

    data_root = Path(current_app.config["DATA_ROOT"]).resolve()
    source_path = (data_root / source_file.storage_path).resolve()
    if not source_path.is_relative_to(data_root):
        raise ImporterError("Source file path is outside DATA_ROOT")
    if not source_path.is_file():
        raise ImporterError("Source file is missing")
    return source_path


def load_json_source(source_file: UploadedFile, user_id: int) -> dict[str, Any]:
    source_path = source_file_path(source_file, user_id)
    try:
        document = json.loads(source_path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ImporterError("The uploaded file is not valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ImporterError("The imported JSON must be an object")
    return document
