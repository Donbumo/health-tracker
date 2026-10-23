from flask import Blueprint


wellness_bp = Blueprint("wellness", __name__)

from app.wellness import routes  # noqa: E402, F401
from app.wellness import guided_routes  # noqa: E402, F401
