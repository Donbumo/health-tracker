import os
from pathlib import Path

import pytest
from flask import request

from app import create_app


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


def test_gunicorn_qa_defaults_are_explicit_and_logs_remain_visible():
    entrypoint = (BACKEND_ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")

    for option in (
        "--timeout",
        "--graceful-timeout",
        "--keep-alive",
        "--access-logfile -",
        "--error-logfile -",
        "--capture-output",
    ):
        assert option in entrypoint
    compose_path = PROJECT_ROOT / "docker-compose.yml"
    if compose_path.is_file():
        compose = compose_path.read_text(encoding="utf-8")
        assert "GUNICORN_TIMEOUT: ${GUNICORN_TIMEOUT:-60}" in compose
        assert "GUNICORN_KEEP_ALIVE: ${GUNICORN_KEEP_ALIVE:-5}" in compose
        assert "AI_PROVIDER_TIMEOUT_SECONDS: ${AI_PROVIDER_TIMEOUT_SECONDS:-20}" in compose
        assert "AI_OVERALL_DEADLINE_SECONDS: ${AI_OVERALL_DEADLINE_SECONDS:-50}" in compose
    else:
        assert os.environ["GUNICORN_TIMEOUT"] == "60"
        assert os.environ["GUNICORN_KEEP_ALIVE"] == "5"


def _proxy_probe_app(app, **overrides):
    config = {
        "TESTING": True,
        "SECRET_KEY": "qa-proxy-secret-key-that-is-long-enough",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_ENGINE_OPTIONS": {},
        "DATA_ROOT": app.config["DATA_ROOT"],
        "UPLOAD_ROOT": app.config["UPLOAD_ROOT"],
        "GENERATED_UPLOAD_ROOT": app.config["GENERATED_UPLOAD_ROOT"],
        "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
        **overrides,
    }
    probe = create_app(config)

    @probe.get("/_qa/proxy")
    def proxy_probe():
        return {"scheme": request.scheme, "remote_addr": request.remote_addr}

    return probe


def test_forwarded_proto_is_ignored_by_default_and_trusted_for_one_configured_hop(app):
    disabled = _proxy_probe_app(app)
    assert disabled.test_client().get(
        "/_qa/proxy", headers={"X-Forwarded-Proto": "https"}
    ).get_json()["scheme"] == "http"

    enabled = _proxy_probe_app(app, PROXY_FIX_X_PROTO=1)
    assert enabled.test_client().get(
        "/_qa/proxy", headers={"X-Forwarded-Proto": "https"}
    ).get_json()["scheme"] == "https"


def test_proxy_hop_counts_are_bounded(app):
    with pytest.raises(RuntimeError, match="between 0 and 2"):
        _proxy_probe_app(app, PROXY_FIX_X_FOR=99)
