from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import ExternalAccount, ExternalImportEvent
from app.services.integrations.accounts import access_token, invalidate_account
from app.services.integrations.base import IntegrationProvider, IntegrationProviderError
from app.services.integrations.registry import provider_registry
from app.services.integrations.sync import delete_external_resource, upsert_normalized_resource


class WebhookPayloadError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def validate_strava_event(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WebhookPayloadError("payload must be an object")
    allowed = {
        "object_type", "object_id", "aspect_type", "updates",
        "owner_id", "subscription_id", "event_time",
    }
    required = {"object_type", "object_id", "aspect_type", "owner_id", "subscription_id", "event_time"}
    if set(payload) - allowed or not required.issubset(payload):
        raise WebhookPayloadError("payload fields are invalid")
    object_type = payload["object_type"]
    aspect_type = payload["aspect_type"]
    if object_type not in {"activity", "athlete"} or aspect_type not in {"create", "update", "delete"}:
        raise WebhookPayloadError("event type is invalid")
    for key in ("object_id", "owner_id", "subscription_id", "event_time"):
        if type(payload[key]) is not int or payload[key] < 0:
            raise WebhookPayloadError(f"{key} is invalid")
    updates = payload.get("updates") or {}
    if not isinstance(updates, dict) or set(updates) - {"title", "type", "private", "authorized"}:
        raise WebhookPayloadError("updates are invalid")
    if object_type == "athlete" and not (
        aspect_type == "update" and updates.get("authorized") == "false"
    ):
        raise WebhookPayloadError("athlete event is unsupported")
    sanitized = {
        "object_type": object_type,
        "object_id": payload["object_id"],
        "aspect_type": aspect_type,
        "owner_id": payload["owner_id"],
        "subscription_id": payload["subscription_id"],
        "event_time": payload["event_time"],
        "updates": {
            key: value
            for key, value in updates.items()
            if isinstance(value, (str, bool, int, float)) or value is None
        },
    }
    return sanitized


def enqueue_strava_event(payload: Any) -> tuple[ExternalImportEvent | None, bool]:
    event = validate_strava_event(payload)
    account = db.session.execute(
        db.select(ExternalAccount).where(
            ExternalAccount.provider == "strava",
            ExternalAccount.provider_account_id == str(event["owner_id"]),
        ).order_by(ExternalAccount.connected_at.desc())
    ).scalars().first()
    if account is None:
        return None, False
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = hashlib.sha256(encoded).hexdigest()
    existing = db.session.execute(
        db.select(ExternalImportEvent).where(
            ExternalImportEvent.provider == "strava",
            ExternalImportEvent.external_account_id == account.id,
            ExternalImportEvent.event_key_sha256 == key,
        )
    ).scalar_one_or_none()
    if existing:
        return existing, True
    row = ExternalImportEvent(
        user_id=account.user_id,
        external_account_id=account.id,
        provider="strava",
        event_key_sha256=key,
        event_type=f"{event['object_type']}.{event['aspect_type']}",
        resource_type="activity" if event["object_type"] == "activity" else "account",
        external_resource_id=str(event["object_id"]),
        payload_json=event,
    )
    try:
        with db.session.begin_nested():
            db.session.add(row)
            db.session.flush()
        db.session.commit()
        return row, False
    except IntegrityError:
        db.session.rollback()
        existing = db.session.execute(
            db.select(ExternalImportEvent).where(
                ExternalImportEvent.provider == "strava",
                ExternalImportEvent.external_account_id == account.id,
                ExternalImportEvent.event_key_sha256 == key,
            )
        ).scalar_one()
        return existing, True


def process_pending_events(
    *, limit: int = 100, provider: IntegrationProvider | None = None
) -> dict[str, int]:
    rows = db.session.execute(
        db.select(ExternalImportEvent).where(
            ExternalImportEvent.status.in_({"pending", "failed"}),
            ExternalImportEvent.attempts < 5,
        ).order_by(ExternalImportEvent.created_at, ExternalImportEvent.id).limit(limit)
    ).scalars().all()
    result = {"processed": 0, "completed": 0, "failed": 0, "ignored": 0}
    for row in rows:
        result["processed"] += 1
        row.status = "processing"
        row.processing_started_at = _now()
        row.attempts += 1
        db.session.commit()
        account = db.session.execute(
            db.select(ExternalAccount).where(
                ExternalAccount.id == row.external_account_id,
                ExternalAccount.user_id == row.user_id,
            )
        ).scalar_one_or_none()
        if account is None:
            row.status = "ignored"
            row.error_code = "account_missing"
            row.processed_at = _now()
            db.session.commit()
            result["ignored"] += 1
            continue
        try:
            if row.event_type == "athlete.update":
                invalidate_account(account)
                outcome = "completed"
            elif row.event_type == "activity.delete":
                delete_external_resource(account, row.external_resource_id)
                outcome = "completed"
            elif row.event_type in {"activity.create", "activity.update"}:
                active_provider = provider or provider_registry.get(row.provider)
                token = access_token(row.user_id, account.id, provider=active_provider)
                account = db.session.get(ExternalAccount, account.id)
                payload, rate = active_provider.fetch_resource(
                    token,
                    resource_type="activity",
                    external_resource_id=row.external_resource_id,
                )
                normalized = active_provider.normalize_resource(
                    resource_type="activity", payload=payload
                )
                upsert_normalized_resource(account, normalized)
                account.last_rate_limit_json = rate
                outcome = "completed"
            else:
                outcome = "ignored"
            row.status = outcome
            row.error_code = None
            row.processed_at = _now()
            db.session.commit()
            result[outcome] += 1
        except Exception as error:
            db.session.rollback()
            row = db.session.get(ExternalImportEvent, row.id)
            row.status = "failed"
            row.error_code = getattr(error, "code", "processing_failed")
            row.processed_at = _now()
            db.session.commit()
            result["failed"] += 1
    return result
