import os
from pathlib import Path


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
    else:
        assert os.environ["GUNICORN_TIMEOUT"] == "60"
        assert os.environ["GUNICORN_KEEP_ALIVE"] == "5"
