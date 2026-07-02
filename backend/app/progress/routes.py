from flask import abort, render_template
from flask_login import current_user, login_required

from app.extensions import db
from app.models import TrainingSession, TrainingSessionExercise
from app.progress import progress_bp
from app.services.overload import exercise_history, session_progress_summary


def _user_session_or_404(session_id: int) -> TrainingSession:
    training_session = db.session.execute(
        db.select(TrainingSession).where(
            TrainingSession.id == session_id,
            TrainingSession.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if training_session is None:
        abort(404)
    return training_session


def _user_exercise_or_404(exercise_id: int) -> TrainingSessionExercise:
    exercise = db.session.execute(
        db.select(TrainingSessionExercise).where(
            TrainingSessionExercise.id == exercise_id,
            TrainingSessionExercise.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if exercise is None or exercise.training_session.user_id != current_user.id:
        abort(404)
    return exercise


@progress_bp.get("/exercises/<int:exercise_id>")
@login_required
def exercise_detail(exercise_id: int):
    exercise = _user_exercise_or_404(exercise_id)
    history = exercise_history(current_user.id, exercise.name)
    return render_template(
        "progress/exercise.html",
        exercise_name=exercise.name,
        history=reversed(history),
    )


@progress_bp.get("/sessions/<int:session_id>")
@login_required
def session_summary(session_id: int):
    training_session = _user_session_or_404(session_id)
    summary = session_progress_summary(training_session, current_user.id)
    return render_template(
        "progress/session.html",
        session=training_session,
        summary=summary,
    )
