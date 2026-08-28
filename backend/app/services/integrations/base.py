from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class IntegrationProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        status: int = 502,
        retryable: bool = False,
        rate_limit: dict[str, list[int]] | None = None,
    ):
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status = status
        self.retryable = retryable
        self.rate_limit = rate_limit or {}


@dataclass(frozen=True)
class CredentialBundle:
    access_token: str
    refresh_token: str
    expires_at: datetime
    scopes: tuple[str, ...] = ()
    account_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderAccountIdentity:
    provider_account_id: str
    display_name: str | None
    display_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderPage:
    items: tuple[dict[str, Any], ...]
    has_more: bool
    rate_limit: dict[str, list[int]] = field(default_factory=dict)


class IntegrationProvider(ABC):
    name: str

    @abstractmethod
    def build_authorization_url(self, *, state: str, redirect_uri: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def exchange_code(self, *, code: str, redirect_uri: str) -> CredentialBundle:
        raise NotImplementedError

    @abstractmethod
    def refresh_credentials(self, refresh_token: str) -> CredentialBundle:
        raise NotImplementedError

    @abstractmethod
    def revoke(self, token: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_account_identity(self, credentials: CredentialBundle) -> ProviderAccountIdentity:
        raise NotImplementedError

    @abstractmethod
    def pull_changes(
        self,
        access_token: str,
        *,
        after: int | None,
        before: int | None,
        page: int,
        per_page: int,
    ) -> ProviderPage:
        raise NotImplementedError

    @abstractmethod
    def fetch_resource(
        self, access_token: str, *, resource_type: str, external_resource_id: str
    ) -> tuple[dict[str, Any], dict[str, list[int]]]:
        raise NotImplementedError

    @abstractmethod
    def normalize_resource(
        self, *, resource_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError
