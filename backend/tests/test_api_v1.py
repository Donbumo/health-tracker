import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app import create_app
from app.api_v1.auth import _signer
from app.api_v1.rate_limit import rate_limiter
from app.extensions import db
from app.models import ApiDevice, ApiRefreshToken, ApiSession, TrainingPlan, TrainingPlanVersion, User


DEVICE_ID = "11111111-1111-4111-8111-111111111111"


def _login_payload(email="test-user", password="test-password", device_id=DEVICE_ID):
    return {
        "email": email,
        "password": password,
        "device": {
            "device_id": device_id,
            "name": "Teléfono ficticio",
            "platform": "android",
            "app_version": "0.6.0",
            "os_version": "QA",
        },
    }


def _api_login(client, **kwargs):
    response = client.post("/api/v1/auth/login", json=_login_payload(**kwargs))
    assert response.status_code == 200
    return response.get_json()["data"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def clear_limiter(user):
    rate_limiter.clear()
    yield
    rate_limiter.clear()


def test_api_health_and_contract_security_headers(client):
    response = client.get("/api/v1/health")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["data"]["status"] == "ok"
    assert payload["meta"]["api_version"] == "1"
    assert payload["meta"]["request_id"]
    assert response.content_type.startswith("application/json")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_api_login_uses_bearer_not_web_cookie(client, app):
    tokens = _api_login(client)
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == app.config["API_ACCESS_TOKEN_SECONDS"]
    with app.app_context():
        claims = _signer().loads(tokens["access_token"])
        stored_user = db.session.execute(db.select(User)).scalar_one()
        assert claims["sub"] == stored_user.public_id
        assert claims["sub"] != str(stored_user.id)
    response = client.get("/api/v1/me", headers=_auth(tokens["access_token"]))
    assert response.status_code == 200
    assert "password_hash" not in json.dumps(response.get_json())
    client.post("/login", data={"username": "test-user", "password": "test-password"})
    denied = client.get("/api/v1/me")
    assert denied.status_code == 401
    assert denied.headers["WWW-Authenticate"].startswith("Bearer")


@pytest.mark.parametrize("email,password", [("missing@example.test", "bad"), ("test-user", "bad")])
def test_api_invalid_credentials_are_indistinguishable(client, email, password):
    response = client.post("/api/v1/auth/login", json=_login_payload(email=email, password=password))
    assert response.status_code == 401
    assert response.get_json()["error"] == {
        "code": "invalid_credentials",
        "message": "Credenciales inválidas.",
        "details": {},
    }


def test_api_rejects_content_type_device_uuid_platform_and_deep_json(client):
    assert client.post("/api/v1/auth/login", data="{}").status_code == 415
    bad_uuid = _login_payload(device_id="not-a-uuid")
    assert client.post("/api/v1/auth/login", json=bad_uuid).status_code == 400
    bad_platform = _login_payload()
    bad_platform["device"]["platform"] = "desktop-root"
    assert client.post("/api/v1/auth/login", json=bad_platform).status_code == 400
    deep = {}
    cursor = deep
    for _ in range(15):
        cursor["child"] = {}
        cursor = cursor["child"]
    assert client.post("/api/v1/auth/login", json=deep).status_code == 400


def test_access_token_tamper_wrong_audience_expiry_and_query_rejected(client, app):
    tokens = _api_login(client)
    token = tokens["access_token"]
    assert client.get("/api/v1/me", headers=_auth(token + "x")).status_code == 401
    assert client.get(f"/api/v1/me?access_token={token}").status_code == 401
    app.config["API_TOKEN_AUDIENCE"] = "other-audience"
    assert client.get("/api/v1/me", headers=_auth(token)).status_code == 401


def test_access_token_expiry_and_wrong_issuer_are_rejected(client, app):
    app.config["API_ACCESS_TOKEN_SECONDS"] = -1
    expired = _api_login(client)["access_token"]
    assert client.get("/api/v1/me", headers=_auth(expired)).status_code == 401
    app.config["API_ACCESS_TOKEN_SECONDS"] = 900
    valid = _api_login(client)["access_token"]
    app.config["API_TOKEN_ISSUER"] = "unexpected-issuer"
    assert client.get("/api/v1/me", headers=_auth(valid)).status_code == 401


def test_signing_key_rotation_invalidates_only_tokens_not_persistent_public_ids(
    client, app, user
):
    _add_plan(app, user)
    first = _api_login(client)
    first_me = client.get(
        "/api/v1/me", headers=_auth(first["access_token"])
    ).get_json()["data"]
    first_routine = client.get(
        "/api/v1/routines/active", headers=_auth(first["access_token"])
    ).get_json()["data"]
    with app.app_context():
        device = db.session.execute(db.select(ApiDevice)).scalar_one()
        original_session = db.session.execute(db.select(ApiSession)).scalar_one()
        stored_ids = {
            "user": db.session.get(User, user).public_id,
            "device": device.public_device_id,
            "session": original_session.public_session_id,
            "family": original_session.token_family_id,
            "plan": db.session.execute(db.select(TrainingPlan)).scalar_one().public_id,
            "version": db.session.execute(
                db.select(TrainingPlanVersion)
            ).scalar_one().public_id,
        }

    app.config["API_TOKEN_SIGNING_KEY"] = (
        "rotated-api-signing-key-for-qa-only-1234567890"
    )
    with app.app_context():
        assert client.get(
            "/api/v1/me", headers=_auth(first["access_token"])
        ).status_code == 401
        assert db.session.get(User, user).public_id == stored_ids["user"]
        assert db.session.execute(db.select(ApiDevice)).scalar_one().public_device_id == stored_ids["device"]
        assert db.session.execute(db.select(ApiSession)).scalar_one().public_session_id == stored_ids["session"]
        assert db.session.execute(db.select(ApiSession)).scalar_one().token_family_id == stored_ids["family"]
        assert db.session.execute(db.select(TrainingPlan)).scalar_one().public_id == stored_ids["plan"]
        assert db.session.execute(db.select(TrainingPlanVersion)).scalar_one().public_id == stored_ids["version"]

    second = _api_login(client)
    second_me = client.get(
        "/api/v1/me", headers=_auth(second["access_token"])
    ).get_json()["data"]
    second_routine = client.get(
        "/api/v1/routines/active", headers=_auth(second["access_token"])
    ).get_json()["data"]
    assert second_me["id"] == first_me["id"] == stored_ids["user"]
    assert second_routine["plan_id"] == first_routine["plan_id"] == stored_ids["plan"]
    assert second_routine["version_id"] == first_routine["version_id"] == stored_ids["version"]
    listed = client.get(
        "/api/v1/devices", headers=_auth(second["access_token"])
    ).get_json()["data"]
    assert listed[0]["device_id"] == stored_ids["device"]
    with app.app_context():
        sessions = db.session.execute(
            db.select(ApiSession).order_by(ApiSession.id)
        ).scalars().all()
        assert sessions[0].public_session_id == stored_ids["session"]
        assert len({item.public_session_id for item in sessions}) == 2


def test_separate_api_signing_key_can_be_required(app, tmp_path):
    with pytest.raises(RuntimeError, match="API_TOKEN_SIGNING_KEY is required"):
        create_app(
            {
                "TESTING": False,
                "SECRET_KEY": "strong-web-key-for-api-requirement-test",
                "API_TOKEN_SIGNING_KEY": None,
                "API_REQUIRE_SEPARATE_SIGNING_KEY": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "SQLALCHEMY_ENGINE_OPTIONS": {},
                "DATA_ROOT": tmp_path / "required-key",
                "UPLOAD_ROOT": tmp_path / "required-key" / "raw",
                "GENERATED_UPLOAD_ROOT": tmp_path / "required-key" / "generated",
                "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
                "APP_TIMEZONE": "UTC",
            }
        )


def test_refresh_rotates_once_and_reuse_revokes_family(client, app):
    first = _api_login(client)
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert refreshed.status_code == 200
    second = refreshed.get_json()["data"]
    assert second["refresh_token"] != first["refresh_token"]
    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reused.status_code == 401
    assert reused.get_json()["error"]["code"] == "refresh_token_reused"
    assert client.get("/api/v1/me", headers=_auth(second["access_token"])).status_code == 401
    with app.app_context():
        session = db.session.execute(db.select(ApiSession)).scalar_one()
        assert session.revoke_reason == "refresh_reuse"
        assert db.session.execute(db.select(ApiRefreshToken).where(ApiRefreshToken.reuse_detected_at.is_not(None))).scalar_one()


def test_concurrent_refresh_has_one_db_claim_one_success_and_revokes_family(
    app, tmp_path
):
    database_path = (tmp_path / "concurrent-refresh.sqlite").as_posix()
    concurrent_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "concurrent-web-secret-key-long-enough",
            "API_TOKEN_SIGNING_KEY": "concurrent-api-signing-key-long-enough",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            "SQLALCHEMY_ENGINE_OPTIONS": {"connect_args": {"timeout": 10}},
            "DATA_ROOT": tmp_path / "concurrent-data",
            "UPLOAD_ROOT": tmp_path / "concurrent-data" / "raw",
            "GENERATED_UPLOAD_ROOT": tmp_path / "concurrent-data" / "generated",
            "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
            "APP_TIMEZONE": "UTC",
            "WTF_CSRF_ENABLED": False,
            "API_RATE_LIMIT_ENABLED": False,
        }
    )
    with concurrent_app.app_context():
        db.create_all()
        concurrent_user = User(username="concurrent-user", role="user")
        concurrent_user.set_password("test-password")
        db.session.add(concurrent_user)
        db.session.commit()
    first = _api_login(concurrent_app.test_client(), email="concurrent-user")
    barrier = Barrier(2)

    def refresh_once():
        with concurrent_app.test_client() as concurrent_client:
            barrier.wait(timeout=5)
            response = concurrent_client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": first["refresh_token"]},
            )
            return response.status_code, response.get_json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: refresh_once(), range(2)))

    assert sorted(status for status, _payload in results) == [200, 401]
    success_payload = next(payload for status, payload in results if status == 200)
    failed_payload = next(payload for status, payload in results if status == 401)
    assert failed_payload["error"]["code"] == "refresh_token_reused"
    assert "access_token" not in json.dumps(failed_payload)
    with concurrent_app.app_context():
        original = db.session.execute(
            db.select(ApiRefreshToken).where(
                ApiRefreshToken.public_token_id == first["refresh_token"].split(".")[1]
            )
        ).scalar_one()
        all_tokens = db.session.execute(db.select(ApiRefreshToken)).scalars().all()
        assert original.replaced_by_id is not None
        assert sum(token.id == original.replaced_by_id for token in all_tokens) == 1, (
            original.replaced_by_id,
            [token.id for token in all_tokens],
        )
        assert len(all_tokens) == 2
        assert original.session.revoked_at is not None
        assert original.session.revoke_reason == "refresh_reuse"
    emitted_access = success_payload["data"]["access_token"]
    assert concurrent_app.test_client().get(
        "/api/v1/me", headers=_auth(emitted_access)
    ).status_code == 401


def test_logout_is_idempotent_and_logout_all_does_not_close_web_session(client):
    tokens = _api_login(client)
    assert client.post("/api/v1/auth/logout", headers=_auth(tokens["access_token"])).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=_auth(tokens["access_token"])).status_code == 200
    second = _api_login(client)
    client.post("/login", data={"username": "test-user", "password": "test-password"})
    assert client.post("/api/v1/auth/logout-all", headers=_auth(second["access_token"])).status_code == 200
    assert client.get("/dashboard").status_code == 200
    assert client.get("/api/v1/me", headers=_auth(second["access_token"])).status_code == 401


def test_devices_are_owner_only_revoke_and_repeat(client, app):
    tokens = _api_login(client)
    listed = client.get("/api/v1/devices", headers=_auth(tokens["access_token"]))
    assert listed.status_code == 200
    assert listed.get_json()["data"][0]["device_id"] == DEVICE_ID
    assert "token" not in json.dumps(listed.get_json())
    assert client.delete("/api/v1/devices/22222222-2222-4222-8222-222222222222", headers=_auth(tokens["access_token"])).status_code == 404
    revoked = client.delete(f"/api/v1/devices/{DEVICE_ID}", headers=_auth(tokens["access_token"]))
    assert revoked.status_code == 200
    # The signed identity can repeat an idempotent revoke even after device revocation.
    repeated = client.delete(f"/api/v1/devices/{DEVICE_ID}", headers=_auth(tokens["access_token"]))
    assert repeated.status_code == 200


def test_api_rate_limit_and_cors_allowlist(client, app):
    app.config.update(API_RATE_LIMIT_LOGIN=1, API_CORS_ORIGINS=("https://companion.example.test",))
    assert client.post("/api/v1/auth/login", json=_login_payload(password="bad")).status_code == 401
    limited = client.post("/api/v1/auth/login", json=_login_payload(password="bad"))
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]
    allowed = client.get("/api/v1/health", headers={"Origin": "https://companion.example.test"})
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://companion.example.test"
    denied = client.get("/api/v1/health", headers={"Origin": "https://evil.example.test"})
    assert "Access-Control-Allow-Origin" not in denied.headers


def test_refresh_expiry_and_revoked_device_are_rejected(client, app):
    tokens = _api_login(client)
    with app.app_context():
        refresh = db.session.execute(db.select(ApiRefreshToken)).scalar_one()
        refresh.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    with app.app_context():
        device = db.session.execute(db.select(ApiDevice)).scalar_one()
        device.revoked_at = datetime.now(timezone.utc)
        db.session.commit()
    assert client.get("/api/v1/me", headers=_auth(tokens["access_token"])).status_code == 401


def test_device_cross_user_is_404_and_metadata_is_allowlisted(client, app):
    first = _api_login(client)
    with app.app_context():
        other = User(username="other-api", email="other-api@example.test", role="user")
        other.set_password("other-test-password")
        db.session.add(other)
        db.session.commit()
    other_tokens = _api_login(
        client,
        email="other-api@example.test",
        password="other-test-password",
        device_id="22222222-2222-4222-8222-222222222222",
    )
    assert client.delete(f"/api/v1/devices/{DEVICE_ID}", headers=_auth(other_tokens["access_token"])).status_code == 404
    listed = client.get("/api/v1/devices", headers=_auth(other_tokens["access_token"])).get_json()["data"]
    assert [item["device_id"] for item in listed] == ["22222222-2222-4222-8222-222222222222"]
    assert "internal" not in json.dumps(listed)
    assert client.get("/api/v1/me", headers=_auth(first["access_token"])).status_code == 200


def test_failed_login_logs_do_not_contain_password_or_full_email(client, caplog):
    secret = "never-log-this-password"
    email = "private-person@example.test"
    response = client.post("/api/v1/auth/login", json=_login_payload(email=email, password=secret))
    assert response.status_code == 401
    logs = caplog.text
    assert secret not in logs
    assert email not in logs
    assert "Authorization" not in logs


def test_api_unknown_route_and_method_use_json_errors(client):
    missing = client.get("/api/v1/not-real")
    assert missing.status_code == 404
    assert missing.is_json
    assert missing.get_json()["error"]["code"] == "not_found"
    wrong_method = client.get("/api/v1/auth/login")
    assert wrong_method.status_code == 405
    assert wrong_method.is_json


def test_cors_preflight_never_uses_wildcard_or_credentials(client, app):
    app.config["API_CORS_ORIGINS"] = ("https://companion.example.test", "*")
    response = client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://companion.example.test", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "https://companion.example.test"
    assert response.headers.get("Access-Control-Allow-Credentials") is None


def _add_plan(app, user_id, name="Plan API", version_number=1):
    document = {
        "schema_version": "1.0", "record_type": "training_plan", "user_id": user_id,
        "source_type": "manual_generated",
        "data": {"name": name, "weeks": [{"week_number": 1, "days": [{
            "day_number": 1, "name": "Día A", "exercises": [{"exercise_order": 1, "name": "Sentadilla", "sets": [{"set_number": 1, "reps": 5, "rest_seconds": 120}]}]
        }]}]},
    }
    with app.app_context():
        plan = TrainingPlan(user_id=user_id, name=name, active_version_number=version_number)
        db.session.add(plan)
        db.session.flush()
        version = TrainingPlanVersion(user_id=user_id, training_plan=plan, version_number=version_number, schema_version="1.0", sha256=(str(version_number) * 64)[:64], content=document)
        db.session.add(version)
        db.session.commit()


def test_me_bootstrap_and_active_routine_are_isolated_deterministic_and_schema_valid(client, app, user):
    _add_plan(app, user)
    tokens = _api_login(client)
    headers = _auth(tokens["access_token"])
    me = client.get("/api/v1/me", headers=headers)
    assert me.status_code == 200
    bootstrap = client.get("/api/v1/companion/bootstrap", headers=headers)
    assert bootstrap.status_code == 200
    capabilities = bootstrap.get_json()["data"]["capabilities"]
    assert capabilities["offline_sync_push"] is False
    assert capabilities["incremental_pull"] is False
    assert capabilities["planned_workouts"] is False
    assert capabilities["backup_zip"] is True
    first = client.get("/api/v1/routines/active", headers=headers)
    second = client.get("/api/v1/routines/active", headers=headers)
    assert first.status_code == 200
    assert first.get_json()["data"] == second.get_json()["data"]
    assert first.get_json()["data"]["selection_policy"] == "most_recent_plan_active_version"
    assert bootstrap.get_json()["data"]["active_routine"]["selection_policy"] == "most_recent_plan_active_version"
    assert first.headers["ETag"]
    schema_root = Path(app.config["SCHEMA_ROOT"])
    for schema_name, data in (
        ("companion_bootstrap", bootstrap.get_json()["data"]),
        ("active_routine_api", first.get_json()["data"]),
    ):
        schema = json.loads((schema_root / f"{schema_name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)


def test_active_routine_no_plan_returns_null(client):
    tokens = _api_login(client)
    response = client.get("/api/v1/routines/active", headers=_auth(tokens["access_token"]))
    assert response.status_code == 200
    assert response.get_json()["data"] is None


def test_api_auth_cleanup_dry_run_and_apply(app):
    runner = app.test_cli_runner()
    with app.app_context():
        user = db.session.execute(db.select(User).where(User.username == "test-user")).scalar_one()
        device = ApiDevice(user=user, public_device_id=DEVICE_ID, name="Expired", platform="unknown")
        session = ApiSession(user=user, device=device, public_session_id="33333333-3333-4333-8333-333333333333", token_family_id="44444444-4444-4444-8444-444444444444", expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        token = ApiRefreshToken(session=session, public_token_id="55555555-5555-4555-8555-555555555555", token_hash="a" * 64, expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        db.session.add_all([device, session, token])
        db.session.commit()
    dry = runner.invoke(args=["api-auth", "cleanup"])
    assert dry.exit_code == 0 and "mode=dry-run" in dry.output and "expired_sessions=1" in dry.output
    applied = runner.invoke(args=["api-auth", "cleanup", "--apply"])
    assert applied.exit_code == 0 and "mode=apply" in applied.output
    with app.app_context():
        assert db.session.execute(db.select(ApiSession)).scalar_one().revoked_at is not None


def test_web_login_logout_and_existing_healthcheck_regression(client):
    assert client.post("/login", data={"username": "test-user", "password": "test-password"}).status_code == 302
    assert client.post("/logout").status_code == 302
    assert client.get("/healthz").status_code == 200
