from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from flask import current_app

from app.extensions import db
from app.models import ExternalAccount, ExternalResource, ExternalSyncCursor
from app.services.activity_interchange import archive_external_activity, upsert_external_activity
from app.services.integrations.accounts import ExternalIntegrationError, access_token
from app.services.integrations.base import IntegrationProvider, IntegrationProviderError
from app.services.integrations.registry import provider_registry


RESOURCE_TYPE = "activity"
PER_PAGE = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _json_value(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _fingerprint(normalized: dict[str, Any]) -> str:
    encoded = json.dumps(
        _json_value(normalized), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cursor(account: ExternalAccount) -> ExternalSyncCursor:
    row = db.session.execute(
        db.select(ExternalSyncCursor).where(
            ExternalSyncCursor.user_id == account.user_id,
            ExternalSyncCursor.external_account_id == account.id,
            ExternalSyncCursor.resource_type == RESOURCE_TYPE,
        )
    ).scalar_one_or_none()
    if row is None:
        row = ExternalSyncCursor(
            user_id=account.user_id,
            external_account_id=account.id,
            resource_type=RESOURCE_TYPE,
        )
        db.session.add(row)
        db.session.flush()
    return row


def _window(cursor: ExternalSyncCursor, mode: str, days: int | None) -> dict[str, Any]:
    if cursor.checkpoint_json:
        return dict(cursor.checkpoint_json)
    end = _now().replace(microsecond=0)
    if mode == "full":
        start = None
    elif mode in {"30", "90"}:
        start = end - timedelta(days=int(mode))
    elif mode == "initial":
        start = end - timedelta(days=days or current_app.config["STRAVA_INITIAL_SYNC_DAYS"])
    elif mode == "incremental" and cursor.cursor_at:
        start = _aware(cursor.cursor_at) - timedelta(
            seconds=current_app.config["STRAVA_SYNC_OVERLAP_SECONDS"]
        )
    elif mode == "incremental":
        start = end - timedelta(days=current_app.config["STRAVA_INITIAL_SYNC_DAYS"])
        mode = "initial"
    else:
        raise ExternalIntegrationError("invalid_sync_range", "El rango de sincronización no es válido.")
    return {
        "mode": mode,
        "after": int(start.timestamp()) if start else None,
        "before": int(end.timestamp()),
        "page": 1,
    }


def _metadata(normalized: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _json_value(normalized[key])
        for key in ("local_started_at", "trainer", "commute", "manual", "visibility")
        if key in normalized
    }


def upsert_normalized_resource(
    account: ExternalAccount, normalized: dict[str, Any]
) -> str:
    external_id = str(normalized["external_resource_id"])
    fingerprint = _fingerprint(normalized)
    resource = db.session.execute(
        db.select(ExternalResource).where(
            ExternalResource.user_id == account.user_id,
            ExternalResource.provider == account.provider,
            ExternalResource.external_account_id == account.id,
            ExternalResource.resource_type == RESOURCE_TYPE,
            ExternalResource.external_resource_id == external_id,
        )
    ).scalar_one_or_none()
    if resource and resource.payload_fingerprint_sha256 == fingerprint and resource.status == "active":
        return "skipped"
    activity, created, changed = upsert_external_activity(
        account.user_id,
        provider=account.provider,
        external_account_public_id=account.public_id,
        external_resource_id=external_id,
        normalized=normalized,
    )
    if resource is None:
        resource = ExternalResource(
            user_id=account.user_id,
            external_account_id=account.id,
            provider=account.provider,
            resource_type=RESOURCE_TYPE,
            external_resource_id=external_id,
            payload_fingerprint_sha256=fingerprint,
        )
        db.session.add(resource)
    resource.activity = activity
    resource.status = "active"
    resource.payload_fingerprint_sha256 = fingerprint
    resource.metadata_json = _metadata(normalized)
    resource.updated_at = _now()
    return "imported" if created else "updated" if changed else "skipped"


def delete_external_resource(account: ExternalAccount, external_resource_id: str) -> str:
    resource = db.session.execute(
        db.select(ExternalResource).where(
            ExternalResource.user_id == account.user_id,
            ExternalResource.external_account_id == account.id,
            ExternalResource.provider == account.provider,
            ExternalResource.resource_type == RESOURCE_TYPE,
            ExternalResource.external_resource_id == str(external_resource_id),
        )
    ).scalar_one_or_none()
    if resource is None or resource.status == "deleted":
        return "skipped"
    if resource.activity is not None:
        archive_external_activity(resource.activity, account.user_id)
    resource.status = "deleted"
    resource.updated_at = _now()
    return "updated"


def sync_account(
    user_id: int,
    account_public_id: str,
    *,
    mode: str = "incremental",
    initial_days: int | None = None,
    provider: IntegrationProvider | None = None,
) -> dict[str, Any]:
    account = db.session.execute(
        db.select(ExternalAccount).where(
            ExternalAccount.user_id == user_id,
            ExternalAccount.public_id == str(account_public_id),
        )
    ).scalar_one_or_none()
    if account is None:
        raise ExternalIntegrationError("not_found", "Integración no encontrada.", status=404)
    if account.status not in {"connected", "sync_error"}:
        raise ExternalIntegrationError("auth_expired", "La conexión externa no está activa.", status=409)
    provider = provider or provider_registry.get(account.provider)
    cursor = _cursor(account)
    checkpoint = _window(cursor, mode, initial_days)
    cursor.checkpoint_json = checkpoint
    cursor.last_checkpoint_at = _now()
    db.session.commit()
    token = access_token(user_id, account.id, provider=provider)
    counts = {"imported": 0, "updated": 0, "skipped": 0, "failed": 0}
    maximum_pages = current_app.config["STRAVA_SYNC_MAX_PAGES"]
    completed = False
    try:
        for _ in range(maximum_pages):
            page_number = int(checkpoint["page"])
            page = provider.pull_changes(
                token,
                after=checkpoint.get("after"),
                before=checkpoint.get("before"),
                page=page_number,
                per_page=PER_PAGE,
            )
            normalized_page = [
                provider.normalize_resource(resource_type=RESOURCE_TYPE, payload=item)
                for item in page.items
            ]
            account = db.session.execute(
                db.select(ExternalAccount).where(
                    ExternalAccount.id == account.id,
                    ExternalAccount.user_id == user_id,
                ).with_for_update()
            ).scalar_one()
            cursor = _cursor(account)
            for normalized in normalized_page:
                outcome = upsert_normalized_resource(account, normalized)
                counts[outcome] += 1
            checkpoint["page"] = page_number + 1
            cursor.checkpoint_json = dict(checkpoint)
            cursor.last_checkpoint_at = _now()
            account.last_rate_limit_json = page.rate_limit
            account.last_sync_at = _now()
            account.last_sync_summary_json = {**counts, "outcome": "in_progress"}
            db.session.commit()
            if not page.has_more:
                completed = True
                break
        if not completed:
            raise IntegrationProviderError(
                "sync_page_limit",
                "La sincronización se pausó de forma segura y continuará en el siguiente intento.",
                status=409,
                retryable=True,
            )
    except IntegrationProviderError as error:
        db.session.rollback()
        account = db.session.execute(
            db.select(ExternalAccount).where(
                ExternalAccount.id == account.id, ExternalAccount.user_id == user_id
            )
        ).scalar_one()
        account.status = "auth_error" if error.status in {401, 403} else "sync_error"
        account.last_error_code = error.code
        account.last_sync_at = _now()
        account.last_rate_limit_json = error.rate_limit
        account.last_sync_summary_json = {**counts, "failed": counts["failed"] + 1, "outcome": error.code}
        account.revision += 1
        db.session.commit()
        raise ExternalIntegrationError(error.code, error.safe_message, status=error.status) from error
    except Exception as error:
        db.session.rollback()
        account = db.session.execute(
            db.select(ExternalAccount).where(
                ExternalAccount.id == account.id, ExternalAccount.user_id == user_id
            )
        ).scalar_one()
        account.status = "sync_error"
        account.last_error_code = "sync_failed"
        account.last_sync_at = _now()
        account.last_sync_summary_json = {
            **counts,
            "failed": counts["failed"] + 1,
            "outcome": "sync_failed",
        }
        account.revision += 1
        db.session.commit()
        raise ExternalIntegrationError(
            "sync_failed",
            "La sincronización externa no pudo completarse; el checkpoint se conservó.",
            status=503,
        ) from error
    account = db.session.execute(
        db.select(ExternalAccount).where(
            ExternalAccount.id == account.id, ExternalAccount.user_id == user_id
        ).with_for_update()
    ).scalar_one()
    cursor = _cursor(account)
    cursor.cursor_at = datetime.fromtimestamp(int(checkpoint["before"]), tz=timezone.utc)
    cursor.checkpoint_json = {}
    cursor.last_checkpoint_at = _now()
    account.status = "connected"
    account.last_error_code = None
    account.last_sync_at = _now()
    account.last_success_at = _now()
    account.last_sync_summary_json = {**counts, "outcome": "success"}
    account.revision += 1
    db.session.commit()
    return dict(account.last_sync_summary_json)
