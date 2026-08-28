from flask import current_app

from app.services.integrations.base import IntegrationProvider, IntegrationProviderError
from app.services.integrations.strava import StravaProvider


class IntegrationProviderRegistry:
    _allowlist = {"strava"}

    def get(self, provider: str) -> IntegrationProvider:
        normalized = str(provider or "").strip().casefold()
        if normalized not in self._allowlist:
            raise IntegrationProviderError(
                "unknown_provider", "El proveedor de integración no está permitido.", status=404
            )
        if normalized == "strava":
            if not current_app.config.get("STRAVA_ENABLED"):
                raise IntegrationProviderError(
                    "provider_disabled", "La integración con Strava no está habilitada.", status=503
                )
            return StravaProvider(
                client_id=str(current_app.config["STRAVA_CLIENT_ID"]),
                client_secret=current_app.config["STRAVA_CLIENT_SECRET"],
                scopes=tuple(current_app.config["STRAVA_SCOPES"]),
                timeout=current_app.config["STRAVA_HTTP_TIMEOUT_SECONDS"],
            )
        raise IntegrationProviderError("unknown_provider", "Proveedor no permitido.", status=404)


provider_registry = IntegrationProviderRegistry()
