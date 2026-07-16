from flask import Blueprint


workout_drafts_bp = Blueprint(
    "workout_drafts", __name__, url_prefix="/workout-session-drafts"
)

from app.workout_drafts import routes  # noqa: E402, F401
