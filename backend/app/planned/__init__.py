from flask import Blueprint


planned_bp = Blueprint("planned", __name__, url_prefix="/planned-workouts")

from app.planned import routes  # noqa: E402,F401
