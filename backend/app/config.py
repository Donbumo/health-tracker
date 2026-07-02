import os
from pathlib import Path

from sqlalchemy.engine import URL


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


class Config:
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
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    DATA_ROOT = Path(os.getenv("DATA_ROOT", PROJECT_ROOT / "data"))
    UPLOAD_ROOT = DATA_ROOT / "uploads" / "raw"
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _as_bool(os.getenv("SESSION_COOKIE_SECURE"))

    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
