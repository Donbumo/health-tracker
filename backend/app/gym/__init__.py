from flask import Blueprint

gym_bp = Blueprint("gym", __name__, url_prefix="/gym")

from app.gym import routes  # noqa: E402,F401
