import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer

from app.api_v1.errors import ApiError
from app.extensions import db
from app.models import ApiDevice, ApiRefreshToken, ApiSession, User


def utcnow():
    return datetime.now(timezone.utc)


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _signer():
    key = current_app.config["API_TOKEN_SIGNING_KEY"]
    return URLSafeSerializer(key, salt="health-tracker-api-access-v1", signer_kwargs={"digest_method": hashlib.sha256})


def _hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _access_token(api_session: ApiSession) -> tuple[str, int]:
    now = utcnow()
    seconds = current_app.config["API_ACCESS_TOKEN_SECONDS"]
    payload = {
        "sub": api_session.user.public_id,
        "sid": api_session.public_session_id,
        "did": api_session.device.public_device_id,
        "fam": api_session.token_family_id,
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=seconds)).timestamp()),
        "iss": current_app.config["API_TOKEN_ISSUER"],
        "aud": current_app.config["API_TOKEN_AUDIENCE"],
        "ver": 1,
    }
    return _signer().dumps(payload), seconds


def _new_refresh(api_session: ApiSession) -> tuple[str, ApiRefreshToken]:
    public_id = str(uuid.uuid4())
    raw = f"rt1.{public_id}.{secrets.token_urlsafe(48)}"
    expires = utcnow() + timedelta(days=current_app.config["API_REFRESH_TOKEN_DAYS"])
    record = ApiRefreshToken(
        session=api_session,
        public_token_id=public_id,
        token_hash=_hash_refresh(raw),
        expires_at=expires,
    )
    db.session.add(record)
    return raw, record


def token_response(api_session: ApiSession, refresh_token: str) -> dict:
    access, expires_in = _access_token(api_session)
    refresh_expires_at = _aware(api_session.expires_at).astimezone(timezone.utc)
    return {
        "access_token": access,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_expires_at": refresh_expires_at.isoformat().replace("+00:00", "Z"),
    }


def create_login_session(user: User, device_data: dict) -> dict:
    now = utcnow()
    device = db.session.execute(
        db.select(ApiDevice).where(
            ApiDevice.user_id == user.id,
            ApiDevice.public_device_id == device_data["device_id"],
        )
    ).scalar_one_or_none()
    if device is None:
        device = ApiDevice(user_id=user.id, public_device_id=device_data["device_id"])
        db.session.add(device)
    device.name = device_data["name"]
    device.platform = device_data["platform"]
    device.app_version = device_data.get("app_version")
    device.os_version = device_data.get("os_version")
    device.last_seen_at = now
    device.revoked_at = None
    session_expiry = now + timedelta(days=current_app.config["API_REFRESH_TOKEN_DAYS"])
    api_session = ApiSession(
        user=user,
        device=device,
        public_session_id=str(uuid.uuid4()),
        token_family_id=str(uuid.uuid4()),
        expires_at=session_expiry,
    )
    db.session.add(api_session)
    raw, _record = _new_refresh(api_session)
    db.session.commit()
    return token_response(api_session, raw)


def parse_access_token(token: str, *, allow_revoked: bool = False) -> tuple[User, ApiSession, dict]:
    try:
        payload = _signer().loads(token)
    except BadData as error:
        raise ApiError("invalid_token", "Token de acceso inválido.", 401) from error
    required = {"sub", "sid", "did", "fam", "iat", "exp", "iss", "aud", "ver"}
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise ApiError("invalid_token", "Token de acceso inválido.", 401)
    now = int(utcnow().timestamp())
    if payload.get("iss") != current_app.config["API_TOKEN_ISSUER"] or payload.get("aud") != current_app.config["API_TOKEN_AUDIENCE"]:
        raise ApiError("invalid_token", "Token de acceso inválido.", 401)
    if payload.get("ver") != 1 or not isinstance(payload.get("exp"), int) or payload["exp"] <= now:
        raise ApiError("token_expired", "Token de acceso expirado.", 401)
    if not isinstance(payload["sub"], str) or len(payload["sub"]) != 36:
        raise ApiError("invalid_token", "Token de acceso inválido.", 401)
    api_session = db.session.execute(
        db.select(ApiSession).join(User, ApiSession.user_id == User.id).where(
            User.public_id == payload["sub"],
            ApiSession.public_session_id == payload["sid"],
            ApiSession.token_family_id == payload["fam"],
        )
    ).scalar_one_or_none()
    user = api_session.user if api_session is not None else None
    if user is None or api_session is None or (api_session.revoked_at is not None and not allow_revoked):
        raise ApiError("session_revoked", "La sesión API no está activa.", 401)
    if _aware(api_session.expires_at) <= utcnow() or (api_session.device.revoked_at is not None and not allow_revoked) or api_session.device.public_device_id != payload["did"]:
        raise ApiError("session_revoked", "La sesión API no está activa.", 401)
    throttle = timedelta(seconds=current_app.config["API_LAST_SEEN_THROTTLE_SECONDS"])
    if utcnow() - _aware(api_session.last_seen_at) >= throttle:
        api_session.last_seen_at = utcnow()
        api_session.device.last_seen_at = utcnow()
        db.session.commit()
    return user, api_session, payload


def rotate_refresh(raw: str) -> dict:
    parts = raw.split(".") if isinstance(raw, str) else []
    if len(parts) != 3 or parts[0] != "rt1":
        raise ApiError("invalid_refresh_token", "Refresh token inválido.", 401)
    record = db.session.execute(
        db.select(ApiRefreshToken).where(ApiRefreshToken.public_token_id == parts[1]).with_for_update()
    ).scalar_one_or_none()
    if record is None or not secrets.compare_digest(record.token_hash, _hash_refresh(raw)):
        raise ApiError("invalid_refresh_token", "Refresh token inválido.", 401)
    api_session = record.session
    now = utcnow()
    if record.used_at is not None:
        _record_refresh_reuse(record, now)
    if record.revoked_at is not None or api_session.revoked_at is not None or _aware(record.expires_at) <= now or _aware(api_session.expires_at) <= now:
        raise ApiError("invalid_refresh_token", "Refresh token inválido o expirado.", 401)
    claimed = db.session.execute(
        db.update(ApiRefreshToken)
        .where(
            ApiRefreshToken.id == record.id,
            ApiRefreshToken.used_at.is_(None),
            ApiRefreshToken.revoked_at.is_(None),
        )
        .values(used_at=now)
    )
    if claimed.rowcount != 1:
        db.session.rollback()
        raced_record = db.session.execute(
            db.select(ApiRefreshToken)
            .where(ApiRefreshToken.public_token_id == parts[1])
            .with_for_update()
        ).scalar_one_or_none()
        if raced_record is not None and secrets.compare_digest(
            raced_record.token_hash, _hash_refresh(raw)
        ):
            _record_refresh_reuse(raced_record, utcnow())
        raise ApiError("invalid_refresh_token", "Refresh token inválido.", 401)
    record.used_at = now
    new_raw, replacement = _new_refresh(api_session)
    db.session.flush()
    record.replaced_by_id = replacement.id
    api_session.last_seen_at = now
    api_session.device.last_seen_at = now
    db.session.commit()
    return token_response(api_session, new_raw)


def _record_refresh_reuse(record: ApiRefreshToken, detected_at: datetime) -> None:
    api_session = record.session
    record.reuse_detected_at = detected_at
    revoke_session(api_session, "refresh_reuse")
    db.session.commit()
    current_app.logger.warning(
        "api_refresh_reuse_detected user_public=%s session=%s",
        api_session.user.public_id[:8],
        api_session.public_session_id[:8],
    )
    raise ApiError("refresh_token_reused", "La familia de tokens fue revocada.", 401)


def revoke_session(api_session: ApiSession, reason: str) -> None:
    if api_session.revoked_at is None:
        api_session.revoked_at = utcnow()
        api_session.revoke_reason = reason[:64]
    for token in api_session.refresh_tokens:
        if token.revoked_at is None:
            token.revoked_at = utcnow()


def revoke_all(user_id: int, reason: str) -> int:
    sessions = db.session.execute(db.select(ApiSession).where(ApiSession.user_id == user_id, ApiSession.revoked_at.is_(None))).scalars().all()
    for api_session in sessions:
        revoke_session(api_session, reason)
    db.session.commit()
    return len(sessions)
