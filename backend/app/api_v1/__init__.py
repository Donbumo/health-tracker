from flask import Blueprint

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

from app.api_v1 import routes  # noqa: E402,F401
from app.api_v1 import mobile_sync_routes  # noqa: E402,F401
