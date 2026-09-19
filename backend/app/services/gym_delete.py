"""Physical deletion only when no session, agenda or draft can be cascaded away.

Caller commits deletion and the existing sync tombstone together. Historical
programs remain intact and can be archived instead. No files are removed.
"""
from sqlalchemy import or_

from app.extensions import db
from app.models import (
    PlannedWorkout, SyncChange, TrainingPlan, TrainingPlanVersion,
    TrainingSession, WorkoutSessionDraft,
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
        (TrainingSession, None,
         'Esta rutina tiene historial. No se puede eliminar sin perder sus referencias; puedes archivarla.'),
        (PlannedWorkout, None,
         'Esta rutina tiene entrenamientos vinculados en la agenda. Se conservan sus referencias; puedes archivarla.'),
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
    if plan is None:
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
        raise GymError('La rutina tiene referencias que deben conservarse.', 409)
    record_sync_change(user_id=user_id, entity_type='training_plan',
                       entity_public_id=public_id, operation='delete',
                       revision=base_revision + 1, payload=None, device_id=None)
    return True
