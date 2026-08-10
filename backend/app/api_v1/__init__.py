from flask import Blueprint

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

from app.api_v1 import routes  # noqa: E402,F401
from app.api_v1 import mobile_sync_routes  # noqa: E402,F401
from app.api_v1 import companion_routes  # noqa: E402,F401
from app.api_v1 import mobile_progress_routes  # noqa: E402,F401
from app.api_v1 import mobile_planning_routes  # noqa: E402,F401
from app.api_v1 import mobile_health_routes  # noqa: E402,F401
from app.api_v1 import portability_routes  # noqa: E402,F401
from app.api_v1 import engagement_routes  # noqa: E402,F401
from app.api_v1 import medical_routes  # noqa: E402,F401
from app.api_v1 import activity_routes  # noqa: E402,F401
from app.api_v1 import ai_routes  # noqa: E402,F401
