import os
from datetime import timedelta
from pathlib import Path

from sqlalchemy.engine import URL


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


class Config:
    APP_VERSION = os.getenv("APP_VERSION") or os.getenv("GIT_COMMIT", "unknown")
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or URL.create(
        drivername="mysql+pymysql",
        username=os.getenv("DB_USER", "health_tracker"),
        password=os.getenv("DB_PASSWORD", "health_tracker"),
        host=os.getenv("DB_HOST", "db"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv("DB_NAME", "health_tracker"),
        query={"charset": "utf8mb4"},
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # create_app keeps READ COMMITTED for MariaDB and removes it for SQLite.
    # That lets the loser of a unique-key idempotency race observe the winner.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "isolation_level": "READ COMMITTED",
    }

    DATA_ROOT = Path(os.getenv("DATA_ROOT", PROJECT_ROOT / "data"))
    UPLOAD_ROOT = DATA_ROOT / "uploads" / "raw"
    GENERATED_UPLOAD_ROOT = DATA_ROOT / "uploads" / "generated"
    SCHEMA_ROOT = Path(os.getenv("SCHEMA_ROOT", PROJECT_ROOT / "schemas"))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "UTC")

    API_TOKEN_SIGNING_KEY = os.getenv("API_TOKEN_SIGNING_KEY")
    API_REQUIRE_SEPARATE_SIGNING_KEY = _as_bool(
        os.getenv("API_REQUIRE_SEPARATE_SIGNING_KEY"), False
    )
    API_TOKEN_ISSUER = os.getenv("API_TOKEN_ISSUER", "health-tracker")
    API_TOKEN_AUDIENCE = os.getenv("API_TOKEN_AUDIENCE", "health-tracker-companion")
    API_ACCESS_TOKEN_SECONDS = int(os.getenv("API_ACCESS_TOKEN_SECONDS", "900"))
    API_REFRESH_TOKEN_DAYS = int(os.getenv("API_REFRESH_TOKEN_DAYS", "30"))
    API_LAST_SEEN_THROTTLE_SECONDS = int(
        os.getenv("API_LAST_SEEN_THROTTLE_SECONDS", "300")
    )
    API_JSON_MAX_BYTES = int(os.getenv("API_JSON_MAX_BYTES", "65536"))
    API_JSON_MAX_DEPTH = int(os.getenv("API_JSON_MAX_DEPTH", "12"))
    API_CORS_ORIGINS = tuple(
        origin.strip()
        for origin in os.getenv("API_CORS_ORIGINS", "").split(",")
        if origin.strip()
    )
    API_RATE_LIMIT_ENABLED = _as_bool(os.getenv("API_RATE_LIMIT_ENABLED"), True)
    API_RATE_LIMIT_LOGIN = int(os.getenv("API_RATE_LIMIT_LOGIN", "10"))
    API_RATE_LIMIT_REFRESH = int(os.getenv("API_RATE_LIMIT_REFRESH", "30"))
    API_RATE_LIMIT_AUTHENTICATED = int(
        os.getenv("API_RATE_LIMIT_AUTHENTICATED", "120")
    )
    API_RATE_LIMIT_WINDOW_SECONDS = int(
        os.getenv("API_RATE_LIMIT_WINDOW_SECONDS", "60")
    )
    SYNC_PUSH_MAX_OPERATIONS = int(os.getenv("SYNC_PUSH_MAX_OPERATIONS", "100"))
    SYNC_PULL_MAX_LIMIT = int(os.getenv("SYNC_PULL_MAX_LIMIT", "200"))
    SYNC_BOOTSTRAP_PAST_DAYS = int(os.getenv("SYNC_BOOTSTRAP_PAST_DAYS", "14"))
    SYNC_BOOTSTRAP_FUTURE_DAYS = int(os.getenv("SYNC_BOOTSTRAP_FUTURE_DAYS", "30"))
    SYNC_IDEMPOTENCY_DAYS = int(os.getenv("SYNC_IDEMPOTENCY_DAYS", "30"))
    SYNC_CHANGE_RETENTION_DAYS = int(os.getenv("SYNC_CHANGE_RETENTION_DAYS", "90"))
    SYNC_TOMBSTONE_RETENTION_DAYS = int(os.getenv("SYNC_TOMBSTONE_RETENTION_DAYS", "90"))
    COMPANION_PACKAGE_MAX_BYTES = int(os.getenv("COMPANION_PACKAGE_MAX_BYTES", "262144"))
    COMPANION_PROGRESS_MAX_EVENTS = int(os.getenv("COMPANION_PROGRESS_MAX_EVENTS", "500"))
    COMPANION_PROGRESS_RETENTION_DAYS = int(os.getenv("COMPANION_PROGRESS_RETENTION_DAYS", "90"))
    COMPANION_TERMINAL_RETENTION_DAYS = int(os.getenv("COMPANION_TERMINAL_RETENTION_DAYS", "365"))

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _as_bool(os.getenv("SESSION_COOKIE_SECURE"))
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    SESSION_REFRESH_EACH_REQUEST = True
    # Flask-WTF passes this value directly to itsdangerous, which expects
    # seconds (not timedelta) in the versions pinned by this project.
    WTF_CSRF_TIME_LIMIT = int(timedelta(hours=8).total_seconds())

    WORKOUT_DRAFT_MAX_BYTES = int(
        os.getenv("WORKOUT_DRAFT_MAX_BYTES", "262144")
    )
    WORKOUT_DRAFT_TTL_DAYS = int(os.getenv("WORKOUT_DRAFT_TTL_DAYS", "7"))
    WORKOUT_DRAFT_SERVER_DEBOUNCE_MS = int(
        os.getenv("WORKOUT_DRAFT_SERVER_DEBOUNCE_MS", "3000")
    )

    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
