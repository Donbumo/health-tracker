import hashlib
import uuid
from datetime import datetime, timezone

from flask import current_app, g, request
from sqlalchemy import or_

from app.api_v1 import api_v1_bp
from app.api_v1.auth import create_login_session, revoke_all, revoke_session, rotate_refresh
from app.api_v1.decorators import bearer_required
from app.api_v1.errors import ApiError, failure, success
from app.api_v1.rate_limit import rate_limiter
from app.api_v1.schemas import json_body, validate_login
from app.api_v1.services import CAPABILITIES, active_routine, rfc3339
from app.extensions import db
from app.models import ApiDevice, User


def _client_key(value: str = "") -> str:
    address = request.remote_addr or "unknown"
    digest = hashlib.sha256(value.casefold().encode()).hexdigest()[:12] if value else "anonymous"
    return f"{address}:{digest}"


def _audit(event: str, user_id: int | None = None, session_id: str | None = None):
    current_app.logger.info("api_event=%s user=%s session=%s", event, user_id or "none", (session_id or "none")[:8])


@api_v1_bp.before_request
def prepare_request():
    g.request_id = str(uuid.uuid4())
    if request.content_length and request.content_length > current_app.config["API_JSON_MAX_BYTES"]:
        raise ApiError("payload_too_large", "El cuerpo supera el límite permitido.", 413)


@api_v1_bp.after_request
def secure_response(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    origin = request.headers.get("Origin")
    allowed = current_app.config.get("API_CORS_ORIGINS", ())
    if origin and origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        response.headers["Vary"] = "Origin"
    if response.status_code == 429 and response.is_json:
        retry = response.get_json().get("error", {}).get("details", {}).get("retry_after")
        if retry:
            response.headers["Retry-After"] = str(retry)
    return response


@api_v1_bp.errorhandler(ApiError)
def handle_api_error(error):
    return failure(error.code, error.message, error.status, error.details)


@api_v1_bp.errorhandler(404)
def api_not_found(_error):
    return failure("not_found", "Recurso no encontrado.", 404)


@api_v1_bp.errorhandler(405)
def api_method_not_allowed(_error):
    return failure("method_not_allowed", "Método no permitido.", 405)


@api_v1_bp.errorhandler(Exception)
def api_internal_error(error):
    current_app.logger.error("api_internal_error request_id=%s type=%s", g.request_id, type(error).__name__)
    return failure("internal_error", "No fue posible completar la solicitud.", 500)


@api_v1_bp.get("/health")
def health():
    return success({"status": "ok", "app": "health-tracker"})


@api_v1_bp.post("/auth/login")
def login():
    payload = json_body()
    email, password, device = validate_login(payload)
    rate_limiter.check("login", _client_key(email), current_app.config["API_RATE_LIMIT_LOGIN"])
    user = db.session.execute(db.select(User).where(or_(User.email == email, User.username == email))).scalar_one_or_none()
    if user is None or not user.check_password(password):
        _audit("api_login_failed")
        raise ApiError("invalid_credentials", "Credenciales inválidas.", 401)
    result = create_login_session(user, device)
    _audit("api_login_success", user.id)
    return success(result)


@api_v1_bp.post("/auth/refresh")
def refresh():
    payload = json_body()
    raw = payload.get("refresh_token")
    rate_limiter.check("refresh", _client_key(str(raw)[:16]), current_app.config["API_RATE_LIMIT_REFRESH"])
    if not isinstance(raw, str) or len(raw) > 512:
        raise ApiError("invalid_refresh_token", "Refresh token inválido.", 401)
    result = rotate_refresh(raw)
    _audit("api_refresh")
    return success(result)


@api_v1_bp.post("/auth/logout")
@bearer_required(allow_revoked=True)
def logout():
    revoke_session(g.api_session, "logout")
    db.session.commit()
    _audit("api_logout", g.api_user.id, g.api_session.public_session_id)
    return success({"revoked": True})


@api_v1_bp.post("/auth/logout-all")
@bearer_required
def logout_all():
    count = revoke_all(g.api_user.id, "logout_all")
    _audit("api_logout_all", g.api_user.id, g.api_session.public_session_id)
    return success({"revoked_sessions": count})


@api_v1_bp.get("/me")
@bearer_required
def me():
    user = g.api_user
    return success({
        "id": user.public_id,
        "email": user.email or user.username,
        "role": user.role,
        "timezone": current_app.config["APP_TIMEZONE"],
        "created_at": rfc3339(user.created_at),
        "capabilities": CAPABILITIES,
    })


@api_v1_bp.get("/devices")
@bearer_required
def devices():
    records = db.session.execute(db.select(ApiDevice).where(ApiDevice.user_id == g.api_user.id).order_by(ApiDevice.created_at.desc())).scalars().all()
    data = [{
        "device_id": item.public_device_id,
        "name": item.name,
        "platform": item.platform,
        "app_version": item.app_version,
        "os_version": item.os_version,
        "created_at": rfc3339(item.created_at),
        "last_seen_at": rfc3339(item.last_seen_at),
        "revoked": item.revoked_at is not None,
        "current_session": item.id == g.api_session.device_id,
    } for item in records]
    return success(data, extra_meta={"pagination": {"page": 1, "per_page": len(data), "has_more": False}})


@api_v1_bp.delete("/devices/<device_id>")
@bearer_required(allow_revoked=True)
def revoke_device(device_id):
    device = db.session.execute(db.select(ApiDevice).where(ApiDevice.user_id == g.api_user.id, ApiDevice.public_device_id == device_id)).scalar_one_or_none()
    if device is None:
        raise ApiError("not_found", "Dispositivo no encontrado.", 404)
    if device.revoked_at is None:
        device.revoked_at = datetime.now(timezone.utc)
    for api_session in device.sessions:
        revoke_session(api_session, "device_revoked")
    db.session.commit()
    _audit("api_device_revoked", g.api_user.id, g.api_session.public_session_id)
    return success({"device_id": device.public_device_id, "revoked": True})


@api_v1_bp.get("/companion/bootstrap")
@bearer_required
def bootstrap():
    routine = active_routine(g.api_user.id)
    return success({
        "api_version": "1",
        "server_time": rfc3339(datetime.now(timezone.utc)),
        "user": {"id": g.api_user.public_id, "timezone": current_app.config["APP_TIMEZONE"]},
        "device": {"device_id": g.api_session.device.public_device_id, "session_id": g.api_session.public_session_id},
        "capabilities": CAPABILITIES,
        "active_routine": None if routine is None else {key: routine[key] for key in ("plan_id", "version_id", "version", "name", "etag", "selection_policy")},
    })


@api_v1_bp.get("/routines/active")
@bearer_required
def routine_active():
    snapshot = active_routine(g.api_user.id)
    response, status = success(snapshot)
    if snapshot:
        response.headers["ETag"] = f'"{snapshot["etag"]}"'
    return response, status
