from flask import Blueprint


integrations_bp = Blueprint("integrations", __name__)

from app.integrations import routes  # noqa: E402,F401
