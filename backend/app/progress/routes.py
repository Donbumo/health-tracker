from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import TrainingSession, TrainingSessionExercise
from app.progress import progress_bp
from app.progress.forms import ExerciseAliasForm
from app.services.exercise_identity import (
    ExerciseIdentityError,
    add_exercise_alias,
    find_exercise_identity,
    get_or_create_exercise,
)
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


@progress_bp.get("")
@login_required
def overview():
    sessions = db.session.execute(
        db.select(TrainingSession)
        .where(TrainingSession.user_id == current_user.id)
        .order_by(TrainingSession.performed_at.desc(), TrainingSession.id.desc())
        .limit(20)
    ).scalars()
    return render_template("progress/index.html", sessions=sessions)


@progress_bp.get("/exercises/<int:exercise_id>")
@login_required
def exercise_detail(exercise_id: int):
    exercise = _user_exercise_or_404(exercise_id)
    identity = find_exercise_identity(current_user.id, exercise.name)
    history = exercise_history(current_user.id, exercise.name)
    return render_template(
        "progress/exercise.html",
        exercise_name=(identity.canonical_name if identity else exercise.name),
        identity=identity,
        alias_form=ExerciseAliasForm(),
        exercise=exercise,
        history=reversed(history),
    )


@progress_bp.post("/exercises/<int:exercise_id>/aliases")
@login_required
def add_alias(exercise_id: int):
    exercise = _user_exercise_or_404(exercise_id)
    form = ExerciseAliasForm()
    if form.validate_on_submit():
        try:
            identity, _created = get_or_create_exercise(
                current_user.id,
                exercise.name,
            )
            _alias, created = add_exercise_alias(
                current_user.id,
                identity.id,
                form.alias_name.data,
            )
        except ExerciseIdentityError as error:
            flash(str(error), "danger")
        else:
            flash(
                "Alias agregado correctamente."
                if created
                else "Ese nombre ya pertenece a la misma identidad.",
                "success" if created else "warning",
            )
    else:
        flash("Ingresa un alias válido de hasta 200 caracteres.", "danger")
    return redirect(url_for("progress.exercise_detail", exercise_id=exercise.id))


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
