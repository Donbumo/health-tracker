from datetime import date

from flask import g, request

from app.api_v1 import api_v1_bp
from app.api_v1.decorators import bearer_required
from app.api_v1.errors import success
from app.services.mobile_progress import (
    history_detail,
    history_page,
    progress_exercise_detail,
    progress_exercises,
    progress_summary,
)
from app.services.mobile_sync import MobileSyncError


def _optional_date(name: str) -> date | None:
    value = request.args.get(name)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise MobileSyncError("invalid_date", f"{name} debe usar YYYY-MM-DD.") from error


@api_v1_bp.get("/mobile/history")
@bearer_required
def mobile_history_list():
    raw_limit = request.args.get("limit", "25")
    try:
        limit = int(raw_limit)
    except ValueError as error:
        raise MobileSyncError("invalid_limit", "limit debe ser un entero.") from error
    return success(
        history_page(
            user_id=g.api_user.id,
            limit=limit,
            cursor=request.args.get("cursor"),
            date_from=_optional_date("date_from"),
            date_to=_optional_date("date_to"),
            exercise_public_id=request.args.get("exercise_public_id"),
        )
    )


@api_v1_bp.get("/mobile/history/<public_id>")
@bearer_required
def mobile_history_detail(public_id):
    return success(history_detail(g.api_user.id, public_id))


@api_v1_bp.get("/mobile/progress/summary")
@bearer_required
def mobile_progress_summary():
    return success(progress_summary(g.api_user.id, request.args.get("range", "30")))


@api_v1_bp.get("/mobile/progress/exercises")
@bearer_required
def mobile_progress_exercises():
    return success(progress_exercises(g.api_user.id, request.args.get("range", "30")))


@api_v1_bp.get("/mobile/progress/exercises/<public_id>")
@bearer_required
def mobile_progress_exercise_detail(public_id):
    return success(
        progress_exercise_detail(
            g.api_user.id, public_id, request.args.get("range", "30")
        )
    )
