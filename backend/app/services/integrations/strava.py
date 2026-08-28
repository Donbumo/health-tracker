from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import json
import math
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.services.integrations.base import (
    CredentialBundle,
    IntegrationProvider,
    IntegrationProviderError,
    ProviderAccountIdentity,
    ProviderPage,
)


AUTH_BASE_URL = "https://www.strava.com"
API_BASE_URL = "https://www.strava.com/api/v3"
MAX_PROVIDER_BODY_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class ProviderHttpResponse:
    status: int
    body: bytes
    headers: dict[str, str]


class UrlLibProviderTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        form: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int,
    ) -> ProviderHttpResponse:
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "Health-Tracker-External-Integrations/1.0",
            **(headers or {}),
        }
        body = None
        if form is not None:
            body = urlencode(form).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url, data=body, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                data = response.read(MAX_PROVIDER_BODY_BYTES + 1)
                if len(data) > MAX_PROVIDER_BODY_BYTES:
                    raise IntegrationProviderError(
                        "malformed_response", "Strava devolvió una respuesta demasiado grande."
                    )
                return ProviderHttpResponse(
                    response.status,
                    data,
                    {key.casefold(): value for key, value in response.headers.items()},
                )
        except HTTPError as error:
            headers_value = {
                key.casefold(): value for key, value in (error.headers.items() if error.headers else [])
            }
            raise _http_error(error.code, headers_value) from error
        except (TimeoutError, socket.timeout) as error:
            raise IntegrationProviderError(
                "provider_timeout", "Strava agotó el tiempo de espera.", status=504, retryable=True
            ) from error
        except URLError as error:
            raise IntegrationProviderError(
                "provider_unavailable", "Strava no está disponible temporalmente.",
                status=503, retryable=True,
            ) from error


def _rate_limit(headers: dict[str, str]) -> dict[str, list[int]]:
    output: dict[str, list[int]] = {}
    for header, name in (
        ("x-ratelimit-limit", "overall_limit"),
        ("x-ratelimit-usage", "overall_usage"),
        ("x-readratelimit-limit", "read_limit"),
        ("x-readratelimit-usage", "read_usage"),
    ):
        value = headers.get(header)
        if not value:
            continue
        try:
            parsed = [int(part.strip()) for part in value.split(",")]
        except ValueError:
            continue
        if len(parsed) == 2 and all(number >= 0 for number in parsed):
            output[name] = parsed
    return output


def _http_error(status: int, headers: dict[str, str]) -> IntegrationProviderError:
    rate = _rate_limit(headers)
    if status == 401:
        return IntegrationProviderError(
            "auth_expired", "La autorización de Strava expiró.", status=401, rate_limit=rate
        )
    if status == 403:
        return IntegrationProviderError(
            "missing_scope", "Strava rechazó el acceso solicitado.", status=403, rate_limit=rate
        )
    if status == 404:
        return IntegrationProviderError(
            "resource_not_found", "El recurso de Strava ya no está disponible.",
            status=404, rate_limit=rate,
        )
    if status == 429:
        return IntegrationProviderError(
            "rate_limited", "Strava alcanzó el límite temporal de solicitudes.",
            status=429, retryable=True, rate_limit=rate,
        )
    if status >= 500:
        return IntegrationProviderError(
            "provider_unavailable", "Strava no está disponible temporalmente.",
            status=503, retryable=True, rate_limit=rate,
        )
    return IntegrationProviderError(
        "provider_rejected", "Strava rechazó la solicitud.", status=502, rate_limit=rate
    )


def _json(response: ProviderHttpResponse) -> Any:
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IntegrationProviderError(
            "malformed_response", "Strava devolvió una respuesta no válida."
        ) from error


def _required_text(payload: dict[str, Any], key: str, maximum: int) -> str:
    value = payload.get(key)
    if value is None:
        raise IntegrationProviderError("malformed_response", "Strava devolvió una respuesta incompleta.")
    value = str(value).strip()
    if not value or len(value) > maximum:
        raise IntegrationProviderError("malformed_response", "Strava devolvió una respuesta no válida.")
    return value


def _timestamp(value: Any, key: str) -> datetime:
    try:
        parsed = datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError) as error:
        raise IntegrationProviderError(
            "malformed_response", f"Strava devolvió {key} no válido."
        ) from error
    return parsed


class StravaProvider(IntegrationProvider):
    name = "strava"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        scopes: tuple[str, ...],
        timeout: int,
        transport=None,
    ):
        self.client_id = client_id
        self._client_secret = client_secret
        self.scopes = scopes
        self.timeout = timeout
        self._transport = transport or UrlLibProviderTransport()

    def build_authorization_url(self, *, state: str, redirect_uri: str) -> str:
        return f"{AUTH_BASE_URL}/oauth/authorize?{urlencode({
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'approval_prompt': 'auto',
            'scope': ','.join(self.scopes),
            'state': state,
        })}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> CredentialBundle:
        response = self._transport.request(
            "POST",
            f"{AUTH_BASE_URL}/oauth/token",
            form={
                "client_id": self.client_id,
                "client_secret": self._client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=self.timeout,
        )
        return self._credentials(_json(response), require_account=True)

    def refresh_credentials(self, refresh_token: str) -> CredentialBundle:
        response = self._transport.request(
            "POST",
            f"{AUTH_BASE_URL}/oauth/token",
            form={
                "client_id": self.client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=self.timeout,
        )
        return self._credentials(_json(response), require_account=False)

    def revoke(self, token: str) -> None:
        basic = base64.b64encode(
            f"{self.client_id}:{self._client_secret}".encode("utf-8")
        ).decode("ascii")
        self._transport.request(
            "POST",
            f"{AUTH_BASE_URL}/oauth/revoke",
            form={"token": token},
            headers={"Authorization": f"Basic {basic}"},
            timeout=self.timeout,
        )

    def get_account_identity(self, credentials: CredentialBundle) -> ProviderAccountIdentity:
        athlete = credentials.account_payload
        if not athlete:
            response = self._transport.request(
                "GET",
                f"{API_BASE_URL}/athlete",
                headers={"Authorization": f"Bearer {credentials.access_token}"},
                timeout=self.timeout,
            )
            athlete = _json(response)
        if not isinstance(athlete, dict):
            raise IntegrationProviderError("malformed_response", "Strava devolvió una identidad no válida.")
        account_id = _required_text(athlete, "id", 128)
        names = [str(athlete.get(key) or "").strip() for key in ("firstname", "lastname")]
        display = " ".join(value for value in names if value)[:160] or None
        return ProviderAccountIdentity(account_id, display, {})

    def pull_changes(
        self,
        access_token: str,
        *,
        after: int | None,
        before: int | None,
        page: int,
        per_page: int,
    ) -> ProviderPage:
        query: dict[str, str | int] = {"page": page, "per_page": per_page}
        if after is not None:
            query["after"] = after
        if before is not None:
            query["before"] = before
        response = self._transport.request(
            "GET",
            f"{API_BASE_URL}/athlete/activities?{urlencode(query)}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self.timeout,
        )
        payload = _json(response)
        if not isinstance(payload, list) or len(payload) > per_page or any(
            not isinstance(item, dict) for item in payload
        ):
            raise IntegrationProviderError("malformed_response", "Strava devolvió una página no válida.")
        return ProviderPage(tuple(payload), len(payload) == per_page, _rate_limit(response.headers))

    def fetch_resource(
        self, access_token: str, *, resource_type: str, external_resource_id: str
    ) -> tuple[dict[str, Any], dict[str, list[int]]]:
        if resource_type != "activity" or not external_resource_id.isdigit():
            raise IntegrationProviderError("unsupported_resource", "El recurso externo no está soportado.", status=400)
        response = self._transport.request(
            "GET",
            f"{API_BASE_URL}/activities/{external_resource_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self.timeout,
        )
        payload = _json(response)
        if not isinstance(payload, dict):
            raise IntegrationProviderError("malformed_response", "Strava devolvió un recurso no válido.")
        return payload, _rate_limit(response.headers)

    def normalize_resource(
        self, *, resource_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if resource_type != "activity":
            raise IntegrationProviderError("unsupported_resource", "El recurso externo no está soportado.", status=400)
        return _normalize_activity(payload)

    @staticmethod
    def _credentials(payload: Any, *, require_account: bool) -> CredentialBundle:
        if not isinstance(payload, dict):
            raise IntegrationProviderError("malformed_response", "Strava devolvió credenciales no válidas.")
        access = _required_text(payload, "access_token", 2048)
        refresh = _required_text(payload, "refresh_token", 2048)
        expires = _timestamp(payload.get("expires_at"), "expires_at")
        scope_value = payload.get("scope", "")
        if not isinstance(scope_value, str):
            raise IntegrationProviderError("malformed_response", "Strava devolvió scopes no válidos.")
        scopes = tuple(sorted({value for value in scope_value.replace(",", " ").split() if value}))
        athlete = payload.get("athlete") or {}
        if require_account and not isinstance(athlete, dict):
            raise IntegrationProviderError("malformed_response", "Strava devolvió una identidad no válida.")
        return CredentialBundle(access, refresh, expires, scopes, athlete)


def _parse_datetime(value: Any, key: str) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise IntegrationProviderError("malformed_response", f"Strava devolvió {key} no válido.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise IntegrationProviderError("malformed_response", f"Strava devolvió {key} no válido.") from error
    if parsed.tzinfo is None:
        raise IntegrationProviderError("malformed_response", f"Strava devolvió {key} sin zona horaria.")
    return parsed.astimezone(timezone.utc)


def _number(payload: dict[str, Any], key: str, *, integer: bool = False, maximum: float | None = None):
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IntegrationProviderError("malformed_response", f"Strava devolvió {key} no válido.")
    value = float(value)
    if not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        raise IntegrationProviderError("malformed_response", f"Strava devolvió {key} fuera de rango.")
    return int(value) if integer else value


def _bool(payload: dict[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if type(value) is not bool:
        raise IntegrationProviderError("malformed_response", f"Strava devolvió {key} no válido.")
    return value


def _utc_offset(payload: dict[str, Any]) -> int | None:
    value = payload.get("utc_offset")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IntegrationProviderError("malformed_response", "Strava devolvió utc_offset no válido.")
    value = float(value)
    if not math.isfinite(value) or not -14 * 3600 <= value <= 14 * 3600:
        raise IntegrationProviderError("malformed_response", "Strava devolvió utc_offset fuera de rango.")
    return int(value)


def _discipline(sport_type: str, trainer: bool | None) -> str:
    normalized = sport_type.casefold()
    if normalized in {"virtualride", "indoorcycling"} or (trainer and "ride" in normalized):
        return "indoor_cycling"
    if "ride" in normalized or "cycling" in normalized:
        return "cycling"
    if "run" in normalized:
        return "running"
    if normalized == "walk":
        return "walking"
    if normalized == "hike":
        return "hiking"
    if normalized in {"weighttraining", "workout", "crossfit"}:
        return "strength"
    return "other"


def _normalize_activity(payload: dict[str, Any]) -> dict[str, Any]:
    external_id = _required_text(payload, "id", 128)
    if not external_id.isdigit() or int(external_id) <= 0:
        raise IntegrationProviderError("malformed_response", "Strava devolvió un activity id no válido.")
    name = _required_text(payload, "name", 200)
    sport_type = str(payload.get("sport_type") or payload.get("type") or "Other").strip()
    if not sport_type or len(sport_type) > 128:
        raise IntegrationProviderError("malformed_response", "Strava devolvió un sport type no válido.")
    started_at = _parse_datetime(payload.get("start_date"), "start_date")
    local_value = payload.get("start_date_local")
    if local_value is not None and (not isinstance(local_value, str) or len(local_value) > 64):
        raise IntegrationProviderError("malformed_response", "Strava devolvió start_date_local no válido.")
    timezone_name = payload.get("timezone")
    if timezone_name is not None:
        if not isinstance(timezone_name, str):
            raise IntegrationProviderError("malformed_response", "Strava devolvió timezone no válido.")
        timezone_name = timezone_name.strip()[:64] or None
    utc_offset_seconds = _utc_offset(payload)
    trainer = _bool(payload, "trainer")
    commute = _bool(payload, "commute")
    manual = _bool(payload, "manual")
    visibility = payload.get("visibility")
    if visibility is not None and (not isinstance(visibility, str) or len(visibility) > 32):
        raise IntegrationProviderError("malformed_response", "Strava devolvió visibility no válida.")
    elapsed = _number(payload, "elapsed_time", integer=True, maximum=10_000_000)
    ended_at = started_at + timedelta(seconds=elapsed) if elapsed is not None else None
    normalized = {
        "external_resource_id": external_id,
        "title": name,
        "activity_type": sport_type[:64],
        "original_type": sport_type,
        "discipline": _discipline(sport_type, trainer),
        "started_at": started_at,
        "ended_at": ended_at,
        "local_started_at": local_value,
        "timezone": timezone_name,
        "utc_offset_minutes": int(utc_offset_seconds / 60) if utc_offset_seconds is not None else None,
        "elapsed_time_seconds": elapsed,
        "moving_time_seconds": _number(payload, "moving_time", integer=True, maximum=10_000_000),
        "distance_meters": _number(payload, "distance"),
        "elevation_gain_meters": _number(payload, "total_elevation_gain"),
        "avg_heart_rate_bpm": _number(payload, "average_heartrate", integer=True, maximum=255),
        "max_heart_rate_bpm": _number(payload, "max_heartrate", integer=True, maximum=255),
        "avg_speed_mps": _number(payload, "average_speed"),
        "max_speed_mps": _number(payload, "max_speed"),
        "calories_kcal": _number(payload, "calories"),
        "trainer": trainer,
        "commute": commute,
        "manual": manual,
        "visibility": visibility,
        "source_device": str(payload.get("device_name") or "").strip()[:128] or None,
    }
    return {key: value for key, value in normalized.items() if value is not None}
