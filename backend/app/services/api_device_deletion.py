from dataclasses import dataclass

from app.extensions import db
from app.models import (
    ApiDevice,
    ApiRefreshToken,
    ApiSession,
    CompanionDeviceProfile,
    CompanionProgressEvent,
    CompanionWorkoutDelivery,
    DeviceSyncState,
    IdempotencyRecord,
    PlannedWorkout,
    SyncChange,
    TrainingSession,
    WorkoutSessionDraft,
)


TERMINAL_DELIVERY_STATUSES = frozenset(
    {"completed", "aborted", "failed", "expired", "cancelled"}
)


class ApiDeviceDeletionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ApiDeviceNotFoundError(ApiDeviceDeletionError):
    def __init__(self) -> None:
        super().__init__("not_found", "El dispositivo no existe.")


@dataclass(frozen=True)
class ApiDeviceDeletionResult:
    public_device_id: str
    sessions: int
    refresh_tokens: int
    companion_profiles: int
    companion_deliveries: int
    companion_progress_events: int
    sync_states: int
    idempotency_records: int


def is_api_device_deletable(device: ApiDevice) -> bool:
    return (
        device.revoked_at is not None
        and not any(api_session.revoked_at is None for api_session in device.sessions)
        and all(
            delivery.status in TERMINAL_DELIVERY_STATUSES
            for delivery in device.companion_deliveries
        )
    )


class ApiDeviceDeletionService:
    def delete(
        self, *, user_id: int, public_device_id: str, confirmed: bool
    ) -> ApiDeviceDeletionResult:
        if not confirmed:
            raise ApiDeviceDeletionError(
                "confirmation_required",
                "Confirma explícitamente la eliminación permanente del dispositivo.",
            )

        device = db.session.execute(
            db.select(ApiDevice)
            .where(
                ApiDevice.user_id == user_id,
                ApiDevice.public_device_id == public_device_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if device is None:
            raise ApiDeviceNotFoundError()
        if device.revoked_at is None:
            raise ApiDeviceDeletionError(
                "device_active",
                "Revoca el dispositivo antes de eliminarlo permanentemente.",
            )

        active_session = db.session.execute(
            db.select(ApiSession.id)
            .where(
                ApiSession.device_id == device.id,
                ApiSession.revoked_at.is_(None),
            )
            .with_for_update()
            .limit(1)
        ).scalar_one_or_none()
        if active_session is not None:
            raise ApiDeviceDeletionError(
                "active_session",
                "El dispositivo todavía tiene una sesión API activa.",
            )

        blocking_delivery = db.session.execute(
            db.select(CompanionWorkoutDelivery.id)
            .where(
                CompanionWorkoutDelivery.api_device_id == device.id,
                CompanionWorkoutDelivery.status.not_in(TERMINAL_DELIVERY_STATUSES),
            )
            .with_for_update()
            .limit(1)
        ).scalar_one_or_none()
        if blocking_delivery is not None:
            raise ApiDeviceDeletionError(
                "active_delivery",
                "El dispositivo tiene una entrega Companion pendiente o activa.",
            )

        return self._delete_technical_records(device)

    def _delete_technical_records(
        self, device: ApiDevice
    ) -> ApiDeviceDeletionResult:
        session_ids = db.session.execute(
            db.select(ApiSession.id)
            .where(ApiSession.device_id == device.id)
            .with_for_update()
        ).scalars().all()
        token_ids = (
            db.session.execute(
                db.select(ApiRefreshToken.id).where(
                    ApiRefreshToken.session_id.in_(session_ids)
                )
            ).scalars().all()
            if session_ids
            else []
        )

        if token_ids:
            db.session.execute(
                db.update(ApiRefreshToken)
                .where(ApiRefreshToken.replaced_by_id.in_(token_ids))
                .values(replaced_by_id=None)
            )
        refresh_tokens = self._delete_count(
            ApiRefreshToken,
            ApiRefreshToken.session_id.in_(session_ids) if session_ids else db.false(),
        )
        sessions = self._delete_count(ApiSession, ApiSession.device_id == device.id)

        progress_events = self._delete_count(
            CompanionProgressEvent,
            CompanionProgressEvent.api_device_id == device.id,
        )
        deliveries = self._delete_count(
            CompanionWorkoutDelivery,
            CompanionWorkoutDelivery.api_device_id == device.id,
        )
        profiles = self._delete_count(
            CompanionDeviceProfile,
            CompanionDeviceProfile.api_device_id == device.id,
        )
        sync_states = self._delete_count(
            DeviceSyncState,
            DeviceSyncState.device_id == device.id,
        )
        idempotency_records = self._delete_count(
            IdempotencyRecord,
            IdempotencyRecord.device_id == device.id,
        )

        db.session.execute(
            db.update(TrainingSession)
            .where(TrainingSession.source_device_id == device.id)
            .values(source_device_id=None)
        )
        db.session.execute(
            db.update(PlannedWorkout)
            .where(PlannedWorkout.last_modified_by_device_id == device.id)
            .values(last_modified_by_device_id=None)
        )
        db.session.execute(
            db.update(SyncChange)
            .where(SyncChange.changed_by_device_id == device.id)
            .values(changed_by_device_id=None)
        )
        db.session.execute(
            db.update(WorkoutSessionDraft)
            .where(WorkoutSessionDraft.last_saved_from_device_id == device.id)
            .values(last_saved_from_device_id=None)
        )

        public_device_id = device.public_device_id
        deleted_device = db.session.execute(
            db.delete(ApiDevice).where(ApiDevice.id == device.id)
        )
        if deleted_device.rowcount != 1:
            raise ApiDeviceDeletionError(
                "delete_conflict",
                "El dispositivo cambió durante la eliminación; no se aplicaron cambios.",
            )
        db.session.flush()
        return ApiDeviceDeletionResult(
            public_device_id=public_device_id,
            sessions=sessions,
            refresh_tokens=refresh_tokens,
            companion_profiles=profiles,
            companion_deliveries=deliveries,
            companion_progress_events=progress_events,
            sync_states=sync_states,
            idempotency_records=idempotency_records,
        )

    @staticmethod
    def _delete_count(model, criterion) -> int:
        result = db.session.execute(db.delete(model).where(criterion))
        return result.rowcount or 0
