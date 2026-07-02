import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import current_app
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


class JsonSchemaValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _schema_filename(schema_name: str) -> str:
    if not schema_name or Path(schema_name).name != schema_name:
        raise ValueError("schema_name must not contain a path")
    return schema_name if schema_name.endswith(".schema.json") else f"{schema_name}.schema.json"


@lru_cache(maxsize=32)
def _load_validator(schema_root: str, schema_name: str) -> Draft202012Validator:
    schema_path = Path(schema_root) / _schema_filename(schema_name)
    if not schema_path.is_file():
        raise FileNotFoundError(f"JSON Schema not found: {schema_path}")

    with schema_path.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise RuntimeError(f"Invalid JSON Schema: {schema_path}") from error

    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_json_document(document: dict[str, Any], schema_name: str) -> None:
    validator = _load_validator(str(current_app.config["SCHEMA_ROOT"]), schema_name)
    validation_errors = sorted(
        validator.iter_errors(document),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if not validation_errors:
        return

    messages = []
    for error in validation_errors:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        messages.append(f"{location}: {error.message}")
    raise JsonSchemaValidationError(messages)
