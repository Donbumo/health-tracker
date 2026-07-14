from datetime import date, timedelta

from flask import abort, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import PlannedWorkout, TrainingPlanVersion
from app.planned import planned_bp
from app.planned.forms import (
    PlannedWorkoutActionForm,
    PlannedWorkoutForm,
    PlannedWorkoutRescheduleForm,
)
from app.services.mobile_sync import MobileSyncError, PlannedWorkoutService


def _options(user_id: int):
    versions = db.session.execute(
        db.select(TrainingPlanVersion)
        .where(TrainingPlanVersion.user_id == user_id)
        .order_by(TrainingPlanVersion.created_at.desc())
    ).scalars().all()
    result = []
    for version in versions:
        for week in version.content["data"]["weeks"]:
            for day in week["days"]:
                if day["exercises"]:
                    key = f"{version.id}:{week['week_number']}:{day['day_number']}"
                    label = (
                        f"{version.training_plan.name} · v{version.version_number} · "
                        f"semana {week['week_number']} · {day['name']}"
                    )
                    result.append((key, label))
    return result


def _owned(public_id: str) -> PlannedWorkout:
    record = db.session.execute(
        db.select(PlannedWorkout).where(
            PlannedWorkout.user_id == current_user.id,
            PlannedWorkout.public_id == public_id,
            PlannedWorkout.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if record is None:
        abort(404)
    return record


@planned_bp.get("")
@login_required
def list_workouts():
    start = date.today() - timedelta(days=30)
    end = date.today() + timedelta(days=60)
    records = PlannedWorkoutService.list_range(current_user.id, start, end)
    return render_template(
        "planned/list.html",
        records=records,
        action_form=PlannedWorkoutActionForm(),
        reschedule_form=PlannedWorkoutRescheduleForm(),
    )


@planned_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = PlannedWorkoutForm()
    form.planned_day.choices = _options(current_user.id)
    if not form.is_submitted():
        form.scheduled_for_date.data = date.today()
        form.timezone.data = current_app.config["APP_TIMEZONE"]
    if form.validate_on_submit():
        try:
            version_id, week_number, day_number = (
                int(value) for value in form.planned_day.data.split(":")
            )
            version = db.session.execute(
                db.select(TrainingPlanVersion).where(
                    TrainingPlanVersion.id == version_id,
                    TrainingPlanVersion.user_id == current_user.id,
                )
            ).scalar_one_or_none()
            if version is None:
                abort(404)
            record = PlannedWorkoutService.schedule_from_plan_version(
                user_id=current_user.id,
                plan_public_id=version.training_plan.public_id,
                version_public_id=version.public_id,
                scheduled_for_date=form.scheduled_for_date.data,
                timezone_name=form.timezone.data,
                week_number=week_number,
                day_number=day_number,
            )
            db.session.commit()
        except (MobileSyncError, TypeError, ValueError) as error:
            db.session.rollback()
            flash(f"No fue posible planificar: {error}", "danger")
        else:
            flash("Entrenamiento planificado.", "success")
            return redirect(url_for("planned.list_workouts"))
    return render_template("planned/new.html", form=form)


@planned_bp.post("/<public_id>/reschedule")
@login_required
def reschedule(public_id):
    form = PlannedWorkoutRescheduleForm()
    if not form.validate_on_submit():
        flash("Revisa la fecha y la zona horaria.", "danger")
        return redirect(url_for("planned.list_workouts"))
    record = _owned(public_id)
    try:
        PlannedWorkoutService.reschedule(
            record,
            scheduled_for_date=form.scheduled_for_date.data,
            timezone_name=form.timezone.data,
            base_revision=record.revision,
            device_id=None,
        )
        db.session.commit()
    except MobileSyncError as error:
        db.session.rollback()
        flash(str(error), "danger")
    else:
        flash("Entrenamiento reprogramado.", "success")
    return redirect(url_for("planned.list_workouts"))


def _web_transition(public_id: str, status: str):
    form = PlannedWorkoutActionForm()
    if not form.validate_on_submit():
        abort(400)
    record = _owned(public_id)
    try:
        PlannedWorkoutService.transition(
            record, status, base_revision=record.revision, device_id=None
        )
        db.session.commit()
    except MobileSyncError as error:
        db.session.rollback()
        flash(str(error), "danger")
    else:
        flash("Estado actualizado.", "success")
    return redirect(url_for("planned.list_workouts"))


@planned_bp.post("/<public_id>/skip")
@login_required
def skip(public_id):
    return _web_transition(public_id, "skipped")


@planned_bp.post("/<public_id>/cancel")
@login_required
def cancel(public_id):
    return _web_transition(public_id, "cancelled")
