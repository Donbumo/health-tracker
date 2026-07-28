import importlib.util
from pathlib import Path
import sys
from threading import Thread

from werkzeug.serving import make_server

from app.extensions import db
from app.models import DailyEnergy, WeighIn
from tests.test_mobile_sync import _api_login


SCRIPT_PATH = next(
    candidate
    for candidate in (
        Path(__file__).resolve().parents[2] / "scripts" / "release" / "alpha15_smoke.py",
        Path(__file__).resolve().parents[1] / "scripts" / "release" / "alpha15_smoke.py",
    )
    if candidate.is_file()
)
SPEC = importlib.util.spec_from_file_location("alpha15_smoke", SCRIPT_PATH)
smoke = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = smoke
SPEC.loader.exec_module(smoke)


class FlaskSmokeClient(smoke.SmokeClient):
    def __init__(self, flask_client, token):
        super().__init__("https://qa.example.test", token)
        self.flask_client = flask_client

    def request(self, method, path, payload=None, key=None, authenticated=True):
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.token}"
        if key:
            headers["Idempotency-Key"] = key
        response = self.flask_client.open(path, method=method, json=payload, headers=headers)
        return smoke.Result(response.status_code, response.get_json(), 1)


def _negotiate(client, token):
    response = client.post(
        "/api/v1/companion/negotiate",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "schema_version": "1.0",
            "protocol_versions": ["1.0"],
            "workout_schema_versions": ["1.0"],
            "result_schema_versions": ["1.0"],
            "features": ["offline"],
            "metrics": ["reps", "weight_kg"],
            "limits": {"max_payload_bytes": 65536, "max_progress_events_per_workout": 50},
        },
    )
    assert response.status_code == 201


def test_read_only_smoke_uses_real_routes_without_domain_writes(app, client, user):
    token = _api_login(client)["access_token"]
    _negotiate(client, token)
    messages = []

    smoke.run_read_only(FlaskSmokeClient(client, token), emit=messages.append)

    with app.app_context():
        assert db.session.execute(db.select(WeighIn)).scalars().all() == []
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []
    assert any(message.startswith("PASS readiness") for message in messages)
    assert any(message.startswith("SKIP health_connect_settings") for message in messages)


def test_write_smoke_exercises_idempotency_update_query_delete_and_cleanup(app, client, user):
    token = _api_login(client)["access_token"]
    _negotiate(client, token)
    messages = []

    smoke.run_write(FlaskSmokeClient(client, token), emit=messages.append)

    with app.app_context():
        assert db.session.execute(db.select(WeighIn)).scalars().all() == []
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []
    assert messages[-1] == "PASS write cleanup verified"


def test_final_smoke_uses_real_http_transport_against_ephemeral_server(app, client, user):
    token = _api_login(client)["access_token"]
    _negotiate(client, token)
    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        live = smoke.SmokeClient(f"http://127.0.0.1:{server.server_port}", token, allow_http=True)
        smoke.run_read_only(live, emit=lambda _message: None)
        smoke.run_write(live, emit=lambda _message: None)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    with app.app_context():
        assert db.session.execute(db.select(WeighIn)).scalars().all() == []
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_write_requires_exact_confirmation_and_tls_is_default():
    args = smoke.parse_args(["--base-url", "https://qa.example.test", "--token", "qa", "--write"])
    assert args.confirm_write is None
    assert smoke.main(["--base-url", "https://qa.example.test", "--token", "qa", "--write"]) == 1
    try:
        smoke.SmokeClient("http://qa.example.test", "qa")
    except smoke.SmokeFailure as error:
        assert "HTTPS" in str(error)
    else:
        raise AssertionError("HTTP sin opt-in debió rechazarse")
