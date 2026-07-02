from flask import Blueprint


training_bp = Blueprint("training", __name__, url_prefix="/training-plans")

from app.training import routes  # noqa: E402, F401
