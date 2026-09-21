"""Remove planning without deleting historical facts. Caller owns transaction."""
from datetime import datetime, timezone
from sqlalchemy import or_

from app.extensions import db
from app.models import (
    PlannedWorkout, SyncChange, TrainingPlan, TrainingPlanVersion,
    TrainingSession, WorkoutSessionDraft, TrainingPlanWorkout,
)
from app.services.gym_programs import GymError, lock_user
from app.services.mobile_sync import record_sync_change


def deletion_blocker(plan, *, lock=False):
    versions = db.select(TrainingPlanVersion.id).where(
        TrainingPlanVersion.training_plan_id == plan.id,
        TrainingPlanVersion.user_id == plan.user_id,
    )
    checks = [
        (TrainingSession, TrainingSession.status == 'in_progress',
         'Esta rutina tiene una sesión en curso y no se puede eliminar.'),
        (PlannedWorkout, PlannedWorkout.status == 'in_progress',
         'Hay un entrenamiento de agenda en curso.'),
        (PlannedWorkout, PlannedWorkout.status.in_(('planned', 'in_progress')) & PlannedWorkout.deleted_at.is_(None),
         'Esta rutina tiene entrenamientos pendientes en la agenda. Resuélvelos antes de eliminarla.'),
        (WorkoutSessionDraft, None,
         'Esta rutina tiene un borrador de sesión guardado. Resuélvelo antes de eliminarla.'),
    ]
    for model, condition, reason in checks:
        statement = db.select(model.id).where(model.user_id == plan.user_id, or_(
            model.training_plan_id == plan.id, model.training_plan_version_id.in_(versions),
        )).limit(1)
        if condition is not None:
            statement = statement.where(condition)
        if lock:
            statement = statement.with_for_update()
        if db.session.execute(statement).first():
            return reason
    return None


def delete_program(user_id, public_id, *, base_revision, confirmation):
    if confirmation != 'ELIMINAR' or type(base_revision) is not int or base_revision < 1:
        raise GymError('Escribe ELIMINAR y confirma la revisión mostrada.', 400)
    lock_user(user_id)  # Same lock order as Gym start and import: user, then plan.
    plan = db.session.execute(db.select(TrainingPlan).where(
        TrainingPlan.user_id == user_id, TrainingPlan.public_id == public_id,
    ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if plan is None or plan.deleted_at is not None:
        prior = db.session.execute(db.select(SyncChange.sequence).where(
            SyncChange.user_id == user_id, SyncChange.entity_type == 'training_plan',
            SyncChange.entity_public_id == public_id, SyncChange.operation == 'delete',
            SyncChange.revision == base_revision + 1,
        ).limit(1).with_for_update()).first()
        if prior:
            return False
        raise GymError('Rutina no encontrada.', 404)
    if plan.revision != base_revision:
        raise GymError('La rutina cambió; vuelve a revisar la eliminación.', 409)
    reason = deletion_blocker(plan, lock=True)
    if reason:
        raise GymError(reason, 409)
    # Any cross-owner child is an integrity problem, not permission to cascade.
    for model in (TrainingPlanVersion, TrainingPlanWorkout, TrainingSession, PlannedWorkout, WorkoutSessionDraft):
        if db.session.execute(db.select(model.id).where(
            model.training_plan_id == plan.id, model.user_id != user_id,
        ).limit(1).with_for_update()).first():
            raise GymError('La rutina tiene referencias que deben conservarse.', 409)
    # Defensive integrity check: even inconsistent foreign-owner references must
    # not cascade. Query existence only; never expose another owner's data.
    versions = db.select(TrainingPlanVersion.id).where(TrainingPlanVersion.training_plan_id == plan.id)
    guards = [~db.select(model.id).where(or_(
        model.training_plan_id == plan.id, model.training_plan_version_id.in_(versions),
    )).exists() for model in (TrainingSession, PlannedWorkout, WorkoutSessionDraft)]
    result = db.session.execute(db.delete(TrainingPlan).where(
        TrainingPlan.id == plan.id, TrainingPlan.user_id == user_id, *guards,
    ).execution_options(synchronize_session='fetch'))
    if result.rowcount != 1:
        # Historical sessions/closed agenda keep their immutable versions and FKs.
        # Never change status to archived: deleted is not an editable archive.
        # Recheck foreign version-only references before retaining the anchor.
        for model in (TrainingSession, PlannedWorkout, WorkoutSessionDraft):
            if db.session.execute(db.select(model.id).where(
                model.training_plan_version_id.in_(versions), model.user_id != user_id,
            ).limit(1)).first():
                raise GymError('La rutina tiene referencias que deben conservarse.', 409)
        plan.deleted_at = datetime.now(timezone.utc)
        plan.gym_active = False
        plan.revision = base_revision + 1
        db.session.execute(db.delete(TrainingPlanWorkout).where(
            TrainingPlanWorkout.training_plan_id == plan.id, TrainingPlanWorkout.user_id == user_id,
        ))
    record_sync_change(user_id=user_id, entity_type='training_plan',
                       entity_public_id=public_id, operation='delete',
                       revision=base_revision + 1, payload=None, device_id=None)
    return True
