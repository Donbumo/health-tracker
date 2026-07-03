from flask import Blueprint


body_bp = Blueprint("body", __name__)

from app.body import routes  # noqa: E402, F401
