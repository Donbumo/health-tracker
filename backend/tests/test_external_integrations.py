import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
import time
import uuid
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Activity,
    ExternalAccount,
    ExternalImportEvent,
    ExternalResource,
    ExternalSyncCursor,
    User,
)
from app.services.ai.tools import _activities
from app.services.exporters.user_data import build_user_data_document
from app.services.integrations.accounts import (
    ExternalIntegrationError,
    access_token,
    connect_account,
    disconnect_account,
)
from app.services.integrations.base import (
    CredentialBundle,
    IntegrationProvider,
    IntegrationProviderError,
    ProviderAccountIdentity,
    ProviderPage,
)
from app.services.integrations.registry import provider_registry
from app.services.integrations.security import IntegrationTokenCipher
from app.services.integrations.strava import ProviderHttpResponse, StravaProvider
from app.services.integrations.sync import sync_account, upsert_normalized_resource
from app.services.integrations.webhooks import enqueue_strava_event, process_pending_events
from app.services.portability_export import _serialize_records
from tests.conftest import login


KEY = base64.urlsafe_b64encode(b"q" * 32).decode("ascii")


def _enable(app):
    app.config.update(
        STRAVA_ENABLED=True,
        STRAVA_CLIENT_ID="12345",
        STRAVA_CLIENT_SECRET="fictional-client-secret",
        STRAVA_SCOPES=("read", "activity:read"),
        STRAVA_WEBHOOK_VERIFY_TOKEN="fictional-webhook-token",
        INTEGRATION_TOKEN_ENCRYPTION_KEY=KEY,
        PUBLIC_BASE_URL="http://localhost",
        STRAVA_INITIAL_SYNC_DAYS=90,
        STRAVA_SYNC_OVERLAP_SECONDS=21600,
        STRAVA_SYNC_MAX_PAGES=50,
        STRAVA_HTTP_TIMEOUT_SECONDS=5,
    )


def _activity_payload(activity_id=9001, *, name="Carrera QA", event_time="2026-08-20T12:00:00Z"):
    return {
        "id": activity_id,
        "name": name,
        "sport_type": "Run",
        "start_date": event_time,
        "start_date_local": "2026-08-20T06:00:00Z",
        "timezone": "(GMT-06:00) America/Mexico_City",
        "utc_offset": 0,
        "elapsed_time": 1900,
        "moving_time": 1800,
        "distance": 5100.5,
        "total_elevation_gain": 42.3,
        "average_heartrate": 148.2,
        "max_heartrate": 173,
        "average_speed": 2.83,
        "max_speed": 4.1,
        "calories": 410,
        "trainer": False,
        "commute": False,
        "manual": False,
        "visibility": "everyone",
    }


class FakeProvider(IntegrationProvider):
    name = "strava"

    def __init__(self):
        self.exchange_scopes = ("read", "activity:read")
        self.expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
        self.pages = {1: []}
        self.page_errors = {}
        self.calls = []
        self.refresh_calls = 0
        self.revoked = []
        self.revoke_error = None
        self.fetches = {}
        self.normalize_error = None
        self._normalizer = StravaProvider(
            client_id="12345",
            client_secret="fictional",
            scopes=("read", "activity:read"),
            timeout=5,
            transport=object(),
        )

    def build_authorization_url(self, *, state, redirect_uri):
        return "https://www.strava.com/oauth/authorize?" + urlencode(
            {"state": state, "redirect_uri": redirect_uri}
        )

    def exchange_code(self, *, code, redirect_uri):
        self.calls.append(("exchange", code, redirect_uri))
        return CredentialBundle(
            "access-token-qa",
            "refresh-token-qa",
            self.expires_at,
            self.exchange_scopes,
            {"id": 777, "firstname": "Athlete", "lastname": "QA"},
        )

    def refresh_credentials(self, refresh_token):
        self.refresh_calls += 1
        self.calls.append(("refresh", refresh_token))
        return CredentialBundle(
            f"access-rotated-{self.refresh_calls}",
            f"refresh-rotated-{self.refresh_calls}",
            datetime.now(timezone.utc) + timedelta(hours=6),
        )

    def revoke(self, token):
        self.revoked.append(token)
        if self.revoke_error:
            raise self.revoke_error

    def get_account_identity(self, credentials):
        return ProviderAccountIdentity("777", "Athlete QA", {})

    def pull_changes(self, access_token, *, after, before, page, per_page):
        self.calls.append(("pull", after, before, page, per_page, access_token))
        if page in self.page_errors:
            raise self.page_errors[page]
        items = tuple(self.pages.get(page, []))
        return ProviderPage(items, page in self.pages and (page + 1) in self.pages, {
            "overall_limit": [200, 2000], "overall_usage": [1, 2]
        })

    def fetch_resource(self, access_token, *, resource_type, external_resource_id):
        self.calls.append(("fetch", resource_type, external_resource_id, access_token))
        if external_resource_id not in self.fetches:
            raise IntegrationProviderError("resource_not_found", "No disponible.", status=404)
        return self.fetches[external_resource_id], {"overall_usage": [2, 3]}

    def normalize_resource(self, *, resource_type, payload):
        if self.normalize_error:
            raise self.normalize_error
        return self._normalizer.normalize_resource(resource_type=resource_type, payload=payload)


class FakeStravaTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, *, form=None, headers=None, timeout):
        self.requests.append(
            {"method": method, "url": url, "form": form, "headers": headers or {}, "timeout": timeout}
        )
        return self.responses.pop(0)


@pytest.fixture
def enabled_app(app):
    _enable(app)
    return app


def _connect(enabled_app, user, provider):
    with enabled_app.app_context():
        return connect_account(
            user,
            provider_name="strava",
            code="fictional-code",
            redirect_uri="http://localhost/integrations/strava/callback",
            provider=provider,
        ).public_id


def _webhook(activity_id=9001, aspect="create", event_time=1, object_type="activity"):
    updates = {"authorized": "false"} if object_type == "athlete" else {}
    return {
        "object_type": object_type,
        "object_id": activity_id,
        "aspect_type": "update" if object_type == "athlete" else aspect,
        "updates": updates,
        "owner_id": 777,
        "subscription_id": 12,
        "event_time": event_time,
    }


def test_provider_registry_is_allowlisted_and_config_fails_closed(app):
    with app.app_context():
        with pytest.raises(IntegrationProviderError) as error:
            provider_registry.get("unknown")
        assert error.value.code == "unknown_provider"
    with pytest.raises(RuntimeError, match="INTEGRATION_TOKEN_ENCRYPTION_KEY"):
        create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "integration-config-secret-key-long-enough",
                "STRAVA_ENABLED": True,
                "STRAVA_CLIENT_ID": "123",
                "STRAVA_CLIENT_SECRET": "fictional",
                "STRAVA_WEBHOOK_VERIFY_TOKEN": "fictional",
                "INTEGRATION_TOKEN_ENCRYPTION_KEY": "",
                "PUBLIC_BASE_URL": "http://localhost",
            }
        )


def test_strava_http_contract_is_mocked_for_oauth_refresh_revoke_and_activity_reads():
    payload = _activity_payload(4242)
    transport = FakeStravaTransport(
        [
            ProviderHttpResponse(
                200,
                json.dumps(
                    {
                        "access_token": "fictional-access",
                        "refresh_token": "fictional-refresh",
                        "expires_at": 2_000_000_000,
                        "scope": "read,activity:read",
                        "athlete": {"id": 777, "firstname": "Athlete", "lastname": "QA"},
                    }
                ).encode(),
                {},
            ),
            ProviderHttpResponse(
                200,
                json.dumps(
                    {
                        "access_token": "fictional-access-rotated",
                        "refresh_token": "fictional-refresh-rotated",
                        "expires_at": 2_000_003_600,
                        "scope": "",
                    }
                ).encode(),
                {},
            ),
            ProviderHttpResponse(200, b"{}", {}),
            ProviderHttpResponse(
                200,
                json.dumps([payload]).encode(),
                {
                    "x-ratelimit-limit": "200,2000",
                    "x-ratelimit-usage": "3,40",
                    "x-readratelimit-limit": "100,1000",
                    "x-readratelimit-usage": "2,20",
                },
            ),
            ProviderHttpResponse(200, json.dumps(payload).encode(), {"x-ratelimit-usage": "4,41"}),
        ]
    )
    provider = StravaProvider(
        client_id="12345",
        client_secret="fictional-client-secret",
        scopes=("read", "activity:read"),
        timeout=5,
        transport=transport,
    )

    authorization = parse_qs(urlsplit(provider.build_authorization_url(
        state="fictional-state", redirect_uri="http://localhost/integrations/strava/callback"
    )).query)
    assert authorization["scope"] == ["read,activity:read"]
    assert "activity:write" not in authorization["scope"][0]
    credentials = provider.exchange_code(
        code="fictional-code", redirect_uri="http://localhost/integrations/strava/callback"
    )
    assert credentials.refresh_token == "fictional-refresh"
    assert provider.get_account_identity(credentials).provider_account_id == "777"
    refreshed = provider.refresh_credentials(credentials.refresh_token)
    assert refreshed.refresh_token == "fictional-refresh-rotated"
    provider.revoke(refreshed.refresh_token)
    page = provider.pull_changes(
        refreshed.access_token, after=1_700_000_000, before=1_800_000_000, page=1, per_page=100
    )
    fetched, fetched_rate = provider.fetch_resource(
        refreshed.access_token, resource_type="activity", external_resource_id="4242"
    )

    assert page.items[0]["id"] == 4242
    assert page.rate_limit["overall_usage"] == [3, 40]
    assert page.rate_limit["read_usage"] == [2, 20]
    assert fetched["id"] == 4242
    assert fetched_rate["overall_usage"] == [4, 41]
    revoke_request = transport.requests[2]
    assert revoke_request["url"] == "https://www.strava.com/oauth/revoke"
    assert revoke_request["form"] == {"token": "fictional-refresh-rotated"}
    assert base64.b64decode(
        revoke_request["headers"]["Authorization"].removeprefix("Basic ")
    ).decode() == "12345:fictional-client-secret"


def test_authenticated_token_encryption_rejects_tampering():
    cipher = IntegrationTokenCipher(KEY)
    encrypted = cipher.encrypt("token-plaintext-qa", associated_data="account:1")
    assert encrypted != "token-plaintext-qa"
    assert cipher.decrypt(encrypted, associated_data="account:1") == "token-plaintext-qa"
    with pytest.raises(Exception):
        cipher.decrypt(encrypted, associated_data="account:2")


def test_oauth_state_callback_denied_and_success_encrypts_tokens(
    enabled_app, client, user, monkeypatch
):
    provider = FakeProvider()
    monkeypatch.setattr(provider_registry, "get", lambda name: provider)
    login(client)

    redirect_response = client.post("/integrations/strava/connect")
    assert redirect_response.status_code == 302
    state = parse_qs(urlsplit(redirect_response.headers["Location"]).query)["state"][0]
    denied = client.get(
        "/integrations/strava/callback",
        query_string={"state": state, "error": "access_denied"},
    )
    assert denied.status_code == 302
    with enabled_app.app_context():
        assert db.session.execute(db.select(ExternalAccount)).scalars().all() == []

    redirect_response = client.post("/integrations/strava/connect")
    state = parse_qs(urlsplit(redirect_response.headers["Location"]).query)["state"][0]
    invalid = client.get(
        "/integrations/strava/callback",
        query_string={"state": "wrong-state", "code": "not-used"},
    )
    assert invalid.status_code == 302
    assert not any(call[0] == "exchange" for call in provider.calls)

    redirect_response = client.post("/integrations/strava/connect")
    state = parse_qs(urlsplit(redirect_response.headers["Location"]).query)["state"][0]
    connected = client.get(
        "/integrations/strava/callback",
        query_string={"state": state, "code": "valid-code", "scope": "read,activity:read"},
    )
    assert connected.status_code == 302
    with enabled_app.app_context():
        account = db.session.execute(db.select(ExternalAccount)).scalar_one()
        assert account.status == "connected"
        assert "access-token-qa" not in account.access_token_ciphertext
        assert "refresh-token-qa" not in account.refresh_token_ciphertext
        assert account.last_success_at is not None


def test_connect_post_is_csrf_protected(enabled_app, client, user, monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(provider_registry, "get", lambda name: provider)
    login(client)
    enabled_app.config["WTF_CSRF_ENABLED"] = True
    try:
        response = client.post("/integrations/strava/connect")
        assert response.status_code == 400
        assert not provider.calls
    finally:
        enabled_app.config["WTF_CSRF_ENABLED"] = False


def test_scope_validation_rejects_missing_activity_scope(enabled_app, user):
    provider = FakeProvider()
    provider.exchange_scopes = ("read",)
    with enabled_app.app_context(), pytest.raises(ExternalIntegrationError) as error:
        connect_account(
            user,
            provider_name="strava",
            code="fictional",
            redirect_uri="http://localhost/integrations/strava/callback",
            provider=provider,
        )
    assert error.value.code == "missing_scope"


def test_refresh_rotation_is_persisted_before_reuse(enabled_app, user):
    provider = FakeProvider()
    provider.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    account_id = _connect(enabled_app, user, provider)
    with enabled_app.app_context():
        account = db.session.execute(
            db.select(ExternalAccount).where(ExternalAccount.public_id == account_id)
        ).scalar_one()
        first = access_token(user, account.id, provider=provider)
        second = access_token(user, account.id, provider=provider)
        account = db.session.get(ExternalAccount, account.id)
        cipher = IntegrationTokenCipher(KEY)
        aad = f"external-account:{account.id}:strava"
        assert first == second == "access-rotated-1"
        assert provider.refresh_calls == 1
        assert cipher.decrypt(account.refresh_token_ciphertext, associated_data=aad) == "refresh-rotated-1"


def test_disconnect_revokes_or_retains_only_encrypted_retry_secret(enabled_app, user):
    provider = FakeProvider()
    account_id = _connect(enabled_app, user, provider)
    with enabled_app.app_context():
        account, pending = disconnect_account(user, account_id, provider=provider)
        assert pending is False
        assert provider.revoked == ["refresh-token-qa"]
        assert account.access_token_ciphertext is None
        assert account.refresh_token_ciphertext is None
        assert account.pending_revoke_token_ciphertext is None

    provider = FakeProvider()
    provider.get_account_identity = lambda credentials: ProviderAccountIdentity("778", "Retry QA", {})
    retry_id = _connect(enabled_app, user, provider)
    provider.revoke_error = IntegrationProviderError(
        "provider_unavailable", "Temporal.", status=503, retryable=True
    )
    with enabled_app.app_context():
        account, pending = disconnect_account(user, retry_id, provider=provider)
        assert pending is True
        assert account.status == "disconnected"
        assert account.access_token_ciphertext is None
        assert account.refresh_token_ciphertext is None
        assert account.pending_revoke_token_ciphertext
        assert "refresh-token-qa" not in account.pending_revoke_token_ciphertext


def test_initial_pagination_incremental_overlap_dedup_and_update(enabled_app, user):
    provider = FakeProvider()
    provider.pages = {1: [_activity_payload(1)], 2: [_activity_payload(2)]}
    account_id = _connect(enabled_app, user, provider)
    with enabled_app.app_context():
        first = sync_account(user, account_id, mode="initial", provider=provider)
        assert first == {"imported": 2, "updated": 0, "skipped": 0, "failed": 0, "outcome": "success"}
        assert db.session.execute(db.select(Activity)).scalars().all().__len__() == 2
        cursor = db.session.execute(db.select(ExternalSyncCursor)).scalar_one()
        previous_cursor = cursor.cursor_at

        provider.pages = {1: [_activity_payload(1), _activity_payload(2)]}
        second = sync_account(user, account_id, mode="incremental", provider=provider)
        assert second["skipped"] == 2
        pull = [call for call in provider.calls if call[0] == "pull"][-1]
        assert pull[1] == int(previous_cursor.replace(tzinfo=timezone.utc).timestamp()) - 21600

        provider.pages = {1: [_activity_payload(1, name="Carrera QA actualizada"), _activity_payload(2)]}
        third = sync_account(user, account_id, mode="incremental", provider=provider)
        assert third["updated"] == 1 and third["skipped"] == 1
        assert db.session.execute(db.select(Activity)).scalars().all().__len__() == 2
        assert db.session.execute(
            db.select(Activity).where(Activity.source_activity_id == "1")
        ).scalar_one().title == "Carrera QA actualizada"


def test_failed_page_resumes_from_durable_checkpoint(enabled_app, user):
    provider = FakeProvider()
    provider.pages = {1: [_activity_payload(81)], 2: [_activity_payload(82)]}
    provider.page_errors[2] = IntegrationProviderError(
        "provider_unavailable", "Temporal.", status=503, retryable=True
    )
    account_id = _connect(enabled_app, user, provider)
    with enabled_app.app_context(), pytest.raises(ExternalIntegrationError):
        sync_account(user, account_id, mode="initial", provider=provider)
    with enabled_app.app_context():
        assert db.session.execute(db.select(Activity)).scalars().all().__len__() == 1
        cursor = db.session.execute(db.select(ExternalSyncCursor)).scalar_one()
        assert cursor.checkpoint_json["page"] == 2
    del provider.page_errors[2]
    with enabled_app.app_context():
        result = sync_account(user, account_id, mode="incremental", provider=provider)
        assert result["imported"] == 1
        assert db.session.execute(db.select(Activity)).scalars().all().__len__() == 2
        pulls = [call for call in provider.calls if call[0] == "pull"]
        assert pulls[-1][3] == 2


@pytest.mark.parametrize(
    ("provider_error", "expected_status"),
    [
        (IntegrationProviderError("rate_limited", "Límite.", status=429, retryable=True, rate_limit={"overall_usage": [200, 500]}), "sync_error"),
        (IntegrationProviderError("auth_expired", "Expiró.", status=401), "auth_error"),
        (IntegrationProviderError("provider_unavailable", "Caído.", status=503, retryable=True), "sync_error"),
        (IntegrationProviderError("malformed_response", "Inválido.", status=502), "sync_error"),
    ],
)
def test_sync_preserves_checkpoint_on_provider_failures(enabled_app, user, provider_error, expected_status):
    provider = FakeProvider()
    provider.page_errors[1] = provider_error
    account_id = _connect(enabled_app, user, provider)
    with enabled_app.app_context(), pytest.raises(ExternalIntegrationError) as error:
        sync_account(user, account_id, mode="initial", provider=provider)
    assert error.value.code == provider_error.code
    with enabled_app.app_context():
        account = db.session.execute(
            db.select(ExternalAccount).where(ExternalAccount.public_id == account_id)
        ).scalar_one()
        cursor = db.session.execute(
            db.select(ExternalSyncCursor).where(ExternalSyncCursor.external_account_id == account.id)
        ).scalar_one()
        assert account.status == expected_status
        assert cursor.checkpoint_json["page"] == 1
        assert db.session.execute(db.select(Activity)).scalars().all() == []


def test_cross_user_and_cross_provider_resource_ids_are_isolated(enabled_app, user):
    provider = FakeProvider()
    first_id = _connect(enabled_app, user, provider)
    normalized = provider.normalize_resource(resource_type="activity", payload=_activity_payload(42))
    with enabled_app.app_context():
        other = User(username="external-other", role="user")
        other.set_password("fictional-password")
        db.session.add(other)
        db.session.flush()
        first = db.session.execute(
            db.select(ExternalAccount).where(ExternalAccount.public_id == first_id)
        ).scalar_one()
        second = ExternalAccount(
            user_id=other.id, provider="strava", provider_account_id="other-athlete"
        )
        third = ExternalAccount(
            user_id=user, provider="garmin", provider_account_id="garmin-athlete"
        )
        db.session.add_all([second, third])
        db.session.flush()
        assert upsert_normalized_resource(first, normalized) == "imported"
        assert upsert_normalized_resource(second, normalized) == "imported"
        assert upsert_normalized_resource(third, normalized) == "imported"
        db.session.commit()
        assert db.session.execute(db.select(Activity)).scalars().all().__len__() == 3
        assert db.session.execute(db.select(ExternalResource)).scalars().all().__len__() == 3


def test_webhook_verification_queue_dedupe_and_lifecycle(
    enabled_app, client, user, monkeypatch
):
    provider = FakeProvider()
    account_id = _connect(enabled_app, user, provider)
    monkeypatch.setattr(provider_registry, "get", lambda name: provider)
    denied = client.get(
        "/integrations/strava/webhook",
        query_string={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "challenge-qa",
        },
    )
    assert denied.status_code == 403
    verified = client.get(
        "/integrations/strava/webhook",
        query_string={
            "hub.mode": "subscribe",
            "hub.verify_token": "fictional-webhook-token",
            "hub.challenge": "challenge-qa",
        },
    )
    assert verified.get_json() == {"hub.challenge": "challenge-qa"}
    assert client.post("/integrations/strava/webhook", json={"bad": True}).status_code == 400
    oversized = b'{"padding":"' + (b"x" * (17 * 1024)) + b'"}'
    assert client.post(
        "/integrations/strava/webhook", data=oversized, content_type="application/json"
    ).status_code == 400

    provider.fetches["9001"] = _activity_payload(9001)
    event = _webhook()
    assert client.post("/integrations/strava/webhook", json=event).get_json()["duplicate"] is False
    assert client.post("/integrations/strava/webhook", json=event).get_json()["duplicate"] is True
    with enabled_app.app_context():
        report = process_pending_events(provider=provider)
        assert report["completed"] == 1
        assert db.session.execute(db.select(Activity)).scalars().one().title == "Carrera QA"

    provider.fetches["9001"] = _activity_payload(9001, name="Webhook update QA")
    assert client.post("/integrations/strava/webhook", json=_webhook(aspect="update", event_time=2)).status_code == 200
    with enabled_app.app_context():
        process_pending_events(provider=provider)
        assert db.session.execute(db.select(Activity)).scalar_one().title == "Webhook update QA"

    assert client.post("/integrations/strava/webhook", json=_webhook(aspect="delete", event_time=3)).status_code == 200
    with enabled_app.app_context():
        process_pending_events(provider=provider)
        assert db.session.execute(db.select(Activity)).scalar_one().status == "archived"

    assert client.post(
        "/integrations/strava/webhook",
        json=_webhook(activity_id=777, object_type="athlete", event_time=4),
    ).status_code == 200
    with enabled_app.app_context():
        process_pending_events(provider=provider)
        account = db.session.execute(
            db.select(ExternalAccount).where(ExternalAccount.public_id == account_id)
        ).scalar_one()
        assert account.status == "disconnected"
        assert account.access_token_ciphertext is None
        assert account.refresh_token_ciphertext is None


def test_ai_ui_portability_no_secrets_and_account_delete_cascades(
    enabled_app, client, user
):
    provider = FakeProvider()
    provider.pages = {1: [_activity_payload(31337)]}
    account_id = _connect(enabled_app, user, provider)
    with enabled_app.app_context():
        sync_account(user, account_id, mode="initial", provider=provider)
        account = db.session.get(User, user)
        execution = _activities(account, {"limit": 10})
        assert execution.data["items"][0]["sourceType"] == "external_provider"
        assert execution.data["items"][0]["provider"] == "strava"
        assert execution.evidence[0]["source_type"] == "external_provider"
        exported = build_user_data_document(account, user)
        serialized = json.dumps(exported)
        assert exported["data"]["external_integrations"][0]["provider"] == "strava"
        for forbidden in (
            "access-token-qa", "refresh-token-qa", "access_token_ciphertext",
            "refresh_token_ciphertext", "pending_revoke_token_ciphertext",
        ):
            assert forbidden not in serialized
        portable, _files = _serialize_records(
            account,
            ["external_sources"],
            None,
            None,
            False,
            False,
            False,
            False,
            False,
        )
        portable_json = json.dumps(portable)
        assert portable["external_sources"][0]["data"]["provider"] == "strava"
        assert "access-token-qa" not in portable_json
        assert "refresh-token-qa" not in portable_json

    login(client)
    integrations = client.get("/integrations")
    assert integrations.status_code == 200
    html = integrations.get_data(as_text=True)
    assert "Athlete QA" in html and "access-token-qa" not in html and "refresh-token-qa" not in html
    activities = client.get("/activities").get_data(as_text=True)
    assert "Strava" in activities

    with enabled_app.app_context():
        account = db.session.get(User, user)
        db.session.delete(account)
        db.session.commit()
        assert db.session.execute(db.select(ExternalAccount)).scalars().all() == []
        assert db.session.execute(db.select(ExternalSyncCursor)).scalars().all() == []
        assert db.session.execute(db.select(ExternalResource)).scalars().all() == []
        assert db.session.execute(db.select(ExternalImportEvent)).scalars().all() == []


def test_webhook_unknown_owner_is_acknowledged_without_persistence(enabled_app, client):
    response = client.post("/integrations/strava/webhook", json=_webhook())
    assert response.status_code == 200
    with enabled_app.app_context():
        assert db.session.execute(db.select(ExternalImportEvent)).scalars().all() == []


def test_strava_normalizer_rejects_malformed_provider_response():
    provider = FakeProvider()
    with pytest.raises(IntegrationProviderError) as error:
        provider.normalize_resource(resource_type="activity", payload={"id": 1})
    assert error.value.code == "malformed_response"


@pytest.mark.skipif(
    not Path("/.dockerenv").exists() and os.getenv("INTEGRATIONS_MARIADB_QA") != "1",
    reason="MariaDB integration concurrency runs only in Docker",
)
def test_mariadb_refresh_race_uses_one_rotated_token(app, tmp_path):
    class ConcurrentProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.counter_lock = Lock()

        def refresh_credentials(self, refresh_token):
            with self.counter_lock:
                self.refresh_calls += 1
                number = self.refresh_calls
            time.sleep(0.25)
            return CredentialBundle(
                f"race-access-{number}",
                f"race-refresh-{number}",
                datetime.now(timezone.utc) + timedelta(hours=6),
            )

    mariadb_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "integration-mariadb-secret-key-long-enough",
            "API_TOKEN_SIGNING_KEY": "integration-mariadb-signing-key-long-enough",
            "DATA_ROOT": tmp_path / "integrations-mariadb",
            "UPLOAD_ROOT": tmp_path / "integrations-mariadb" / "raw",
            "GENERATED_UPLOAD_ROOT": tmp_path / "integrations-mariadb" / "generated",
            "PORTABILITY_ROOT": tmp_path / "integrations-mariadb" / "portability",
            "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
            "APP_TIMEZONE": "UTC",
            "WTF_CSRF_ENABLED": False,
            "STRAVA_ENABLED": True,
            "STRAVA_CLIENT_ID": "12345",
            "STRAVA_CLIENT_SECRET": "fictional",
            "STRAVA_SCOPES": ("read", "activity:read"),
            "STRAVA_WEBHOOK_VERIFY_TOKEN": "fictional",
            "INTEGRATION_TOKEN_ENCRYPTION_KEY": KEY,
            "PUBLIC_BASE_URL": "http://localhost",
        }
    )
    provider = ConcurrentProvider()
    provider.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    username = f"integration-race-{uuid.uuid4().hex}"
    with mariadb_app.app_context():
        account = User(username=username, role="user")
        account.set_password("fictional-password")
        db.session.add(account)
        db.session.commit()
        user_id = account.id
        external_id = connect_account(
            user_id,
            provider_name="strava",
            code="fictional",
            redirect_uri="http://localhost/integrations/strava/callback",
            provider=provider,
        ).id
    barrier = Barrier(2)

    def refresh():
        with mariadb_app.app_context():
            barrier.wait(timeout=10)
            return access_token(user_id, external_id, provider=provider)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: refresh(), range(2)))
        assert results == ["race-access-1", "race-access-1"]
        assert provider.refresh_calls == 1
    finally:
        with mariadb_app.app_context():
            db.session.execute(db.delete(User).where(User.id == user_id))
            db.session.commit()
