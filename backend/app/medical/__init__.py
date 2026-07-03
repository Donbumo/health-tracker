from flask import Blueprint


medical_bp = Blueprint("medical", __name__, url_prefix="/medical")

from app.medical import routes  # noqa: E402, F401
