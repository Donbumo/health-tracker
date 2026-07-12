from flask import Blueprint


activities_bp = Blueprint("activities", __name__)

from app.activities import routes  # noqa: E402,F401
