from flask import Blueprint

foods_bp = Blueprint("foods", __name__, url_prefix="/foods")

from app.foods import routes  # noqa
