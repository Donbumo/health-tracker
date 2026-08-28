from datetime import datetime, timedelta, timezone
from typing import Any

from flask import current_app

from app.extensions import db
from app.models import ExternalAccount
from app.services.integrations.base import CredentialBundle, IntegrationProvider, IntegrationProviderError
from app.services.integrations.registry import provider_registry
from app.services.integrations.security import IntegrationSecurityError, IntegrationTokenCipher


class ExternalIntegrationError(RuntimeError):
    def __init__(self, code: str, safe_message: str, *, status: int = 400):
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _aad(account: ExternalAccount) -> str:
    return f"external-account:{account.id}:{account.provider}"


def _cipher() -> IntegrationTokenCipher:
    try:
        return IntegrationTokenCipher(current_app.config["INTEGRATION_TOKEN_ENCRYPTION_KEY"])
    except IntegrationSecurityError as error:
        raise ExternalIntegrationError(
            "credential_store_unavailable",
            "El almacén seguro de integraciones no está disponible.",
            status=503,
        ) from error


def _validate_scopes(scopes: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    granted = tuple(sorted({str(value) for value in scopes if str(value)}))
    requested = set(current_app.config["STRAVA_SCOPES"])
    actual = set(granted)
    required_activity = "activity:read_all" if "activity:read_all" in requested else None
    valid_activity = (
        required_activity in actual
        if required_activity
        else bool({"activity:read", "activity:read_all"} & actual)
    )
    if "read" not in actual or not valid_activity:
        raise ExternalIntegrationError(
            "missing_scope",
            "Strava no concedió todos los permisos de lectura requeridos.",
            status=403,
        )
    if actual & {"activity:write", "profile:write"}:
        raise ExternalIntegrationError(
            "unexpected_scope", "Strava concedió un permiso de escritura no solicitado.", status=403
        )
    return granted


def list_accounts(user_id: int, provider: str | None = None) -> list[ExternalAccount]:
    statement = db.select(ExternalAccount).where(ExternalAccount.user_id == user_id)
    if provider:
        statement = statement.where(ExternalAccount.provider == provider)
    return db.session.execute(
        statement.order_by(ExternalAccount.connected_at.desc(), ExternalAccount.id.desc())
    ).scalars().all()


def owned_account(user_id: int, public_id: str, provider: str | None = None) -> ExternalAccount:
    filters = [ExternalAccount.user_id == user_id, ExternalAccount.public_id == str(public_id)]
    if provider:
        filters.append(ExternalAccount.provider == provider)
    row = db.session.execute(db.select(ExternalAccount).where(*filters)).scalar_one_or_none()
    if row is None:
        raise ExternalIntegrationError("not_found", "Integración no encontrada.", status=404)
    return row


def connect_account(
    user_id: int,
    *,
    provider_name: str,
    code: str,
    redirect_uri: str,
    callback_scopes: tuple[str, ...] = (),
    provider: IntegrationProvider | None = None,
) -> ExternalAccount:
    provider = provider or provider_registry.get(provider_name)
    try:
        credentials = provider.exchange_code(code=code, redirect_uri=redirect_uri)
        scopes = _validate_scopes(credentials.scopes or callback_scopes)
        identity = provider.get_account_identity(credentials)
    except ExternalIntegrationError:
        raise
    except IntegrationProviderError as error:
        raise ExternalIntegrationError(error.code, error.safe_message, status=error.status) from error
    account = db.session.execute(
        db.select(ExternalAccount).where(
            ExternalAccount.user_id == user_id,
            ExternalAccount.provider == provider.name,
            ExternalAccount.provider_account_id == identity.provider_account_id,
        ).with_for_update()
    ).scalar_one_or_none()
    if account is None:
        account = ExternalAccount(
            user_id=user_id,
            provider=provider.name,
            provider_account_id=identity.provider_account_id,
        )
        db.session.add(account)
        db.session.flush()
    elif account.pending_revoke_token_ciphertext:
        pending = _cipher().decrypt(
            account.pending_revoke_token_ciphertext, associated_data=_aad(account)
        )
        try:
            provider.revoke(pending)
        except IntegrationProviderError as error:
            db.session.rollback()
            raise ExternalIntegrationError(
                "remote_revocation_pending",
                "La revocación anterior de Strava sigue pendiente; inténtalo de nuevo.",
                status=503,
            ) from error
        account.pending_revoke_token_ciphertext = None
    cipher = _cipher()
    account.display_name = identity.display_name
    account.display_metadata_json = identity.display_metadata
    account.scopes_json = list(scopes)
    account.access_token_ciphertext = cipher.encrypt(
        credentials.access_token, associated_data=_aad(account)
    )
    account.refresh_token_ciphertext = cipher.encrypt(
        credentials.refresh_token, associated_data=_aad(account)
    )
    account.token_expires_at = credentials.expires_at
    account.token_updated_at = _now()
    account.connected_at = _now()
    account.disconnected_at = None
    account.status = "connected"
    account.last_error_code = None
    account.revision += 1
    db.session.commit()
    return account


def access_token(
    user_id: int,
    account_id: int,
    *,
    provider: IntegrationProvider | None = None,
) -> str:
    account = db.session.execute(
        db.select(ExternalAccount).where(
            ExternalAccount.id == account_id,
            ExternalAccount.user_id == user_id,
        ).with_for_update()
    ).scalar_one_or_none()
    if account is None:
        raise ExternalIntegrationError("not_found", "Integración no encontrada.", status=404)
    if account.status not in {"connected", "sync_error"} or not account.access_token_ciphertext:
        raise ExternalIntegrationError("auth_expired", "La conexión externa no está activa.", status=401)
    cipher = _cipher()
    expires_at = _aware(account.token_expires_at)
    margin = timedelta(seconds=3600)
    if expires_at is not None and expires_at > _now() + margin:
        token = cipher.decrypt(account.access_token_ciphertext, associated_data=_aad(account))
        db.session.commit()
        return token
    if not account.refresh_token_ciphertext:
        account.status = "auth_error"
        account.last_error_code = "auth_expired"
        db.session.commit()
        raise ExternalIntegrationError("auth_expired", "La autorización externa expiró.", status=401)
    refresh = cipher.decrypt(account.refresh_token_ciphertext, associated_data=_aad(account))
    provider = provider or provider_registry.get(account.provider)
    try:
        refreshed = provider.refresh_credentials(refresh)
    except IntegrationProviderError as error:
        account.status = "auth_error" if error.status in {401, 403} else "sync_error"
        account.last_error_code = error.code
        account.revision += 1
        db.session.commit()
        raise ExternalIntegrationError(error.code, error.safe_message, status=error.status) from error
    account.access_token_ciphertext = cipher.encrypt(
        refreshed.access_token, associated_data=_aad(account)
    )
    account.refresh_token_ciphertext = cipher.encrypt(
        refreshed.refresh_token, associated_data=_aad(account)
    )
    account.token_expires_at = refreshed.expires_at
    account.token_updated_at = _now()
    account.last_error_code = None
    account.revision += 1
    db.session.commit()
    return refreshed.access_token


def disconnect_account(
    user_id: int,
    public_id: str,
    *,
    provider: IntegrationProvider | None = None,
) -> tuple[ExternalAccount, bool]:
    account = db.session.execute(
        db.select(ExternalAccount).where(
            ExternalAccount.user_id == user_id,
            ExternalAccount.public_id == str(public_id),
        ).with_for_update()
    ).scalar_one_or_none()
    if account is None:
        raise ExternalIntegrationError("not_found", "Integración no encontrada.", status=404)
    provider = provider or provider_registry.get(account.provider)
    cipher = _cipher()
    token_ciphertext = account.pending_revoke_token_ciphertext or account.refresh_token_ciphertext or account.access_token_ciphertext
    if not token_ciphertext:
        account.status = "disconnected"
        account.disconnected_at = account.disconnected_at or _now()
        db.session.commit()
        return account, False
    token = cipher.decrypt(token_ciphertext, associated_data=_aad(account))
    remote_pending = False
    try:
        provider.revoke(token)
    except IntegrationProviderError:
        remote_pending = True
    account.access_token_ciphertext = None
    account.refresh_token_ciphertext = None
    account.token_expires_at = None
    account.token_updated_at = _now()
    account.status = "disconnected"
    account.disconnected_at = _now()
    account.pending_revoke_token_ciphertext = token_ciphertext if remote_pending else None
    account.last_error_code = "remote_revocation_pending" if remote_pending else None
    account.revision += 1
    db.session.commit()
    return account, remote_pending


def invalidate_account(account: ExternalAccount, *, error_code: str = "deauthorized") -> None:
    account.access_token_ciphertext = None
    account.refresh_token_ciphertext = None
    account.pending_revoke_token_ciphertext = None
    account.token_expires_at = None
    account.status = "disconnected"
    account.disconnected_at = _now()
    account.last_error_code = error_code
    account.revision += 1


def sanitized_account(account: ExternalAccount) -> dict[str, Any]:
    return {
        "public_id": account.public_id,
        "provider": account.provider,
        "provider_account_id": account.provider_account_id,
        "display_name": account.display_name,
        "scopes": list(account.scopes_json or []),
        "status": account.status,
        "connected_at": account.connected_at,
        "last_sync_at": account.last_sync_at,
        "last_success_at": account.last_success_at,
        "last_sync_summary": dict(account.last_sync_summary_json or {}),
        "last_error_code": account.last_error_code,
        "remote_revocation_pending": bool(account.pending_revoke_token_ciphertext),
    }
