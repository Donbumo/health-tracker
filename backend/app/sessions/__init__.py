from flask import Blueprint


sessions_bp = Blueprint("sessions", __name__, url_prefix="/training-sessions")

from app.sessions import routes  # noqa: E402, F401
