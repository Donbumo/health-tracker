from flask import Blueprint

recipes_bp = Blueprint("recipes", __name__, url_prefix="/recipes")

import app.recipes.routes  # noqa: E402,F401