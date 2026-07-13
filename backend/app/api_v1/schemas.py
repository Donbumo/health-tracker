import re
import uuid

from flask import current_app, request

from app.api_v1.errors import ApiError

PLATFORMS = {"android", "ios", "watch", "unknown"}


def _depth(value, level=0):
    if level > current_app.config["API_JSON_MAX_DEPTH"]:
        raise ApiError("json_too_deep", "El JSON excede la profundidad permitida.", 400)
    if isinstance(value, dict):
        for item in value.values():
            _depth(item, level + 1)
    elif isinstance(value, list):
        for item in value:
            _depth(item, level + 1)


def json_body() -> dict:
    if not request.is_json:
        raise ApiError("unsupported_media_type", "Se requiere Content-Type application/json.", 415)
    if request.content_length and request.content_length > current_app.config["API_JSON_MAX_BYTES"]:
        raise ApiError("payload_too_large", "El cuerpo JSON supera el límite permitido.", 413)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("invalid_json", "Se requiere un objeto JSON válido.", 400)
    _depth(payload)
    return payload


def validate_login(payload: dict) -> tuple[str, str, dict]:
    email = str(payload.get("email", "")).strip().casefold()
    password = payload.get("password")
    device = payload.get("device")
    if not email or len(email) > 254 or not isinstance(password, str) or len(password) > 1024 or not isinstance(device, dict):
        raise ApiError("invalid_request", "Los datos de acceso no son válidos.", 400)
    allowed = {"device_id", "name", "platform", "app_version", "os_version"}
    device = {key: device.get(key) for key in allowed if key in device}
    try:
        device_id = str(uuid.UUID(str(device.get("device_id", ""))))
    except ValueError as error:
        raise ApiError("invalid_device", "El identificador del dispositivo no es válido.", 400) from error
    name = re.sub(r"[\x00-\x1f\x7f]", "", str(device.get("name", ""))).strip()
    platform = str(device.get("platform", "unknown")).lower()
    if not name or len(name) > 120 or platform not in PLATFORMS:
        raise ApiError("invalid_device", "Los datos del dispositivo no son válidos.", 400)
    for field, limit in (("app_version", 40), ("os_version", 80)):
        value = device.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise ApiError("invalid_device", "Los datos del dispositivo no son válidos.", 400)
    device.update(device_id=device_id, name=name, platform=platform)
    return email, password, device
