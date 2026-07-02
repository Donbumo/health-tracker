from flask import Blueprint


progress_bp = Blueprint("progress", __name__, url_prefix="/progress")

from app.progress import routes  # noqa: E402, F401
