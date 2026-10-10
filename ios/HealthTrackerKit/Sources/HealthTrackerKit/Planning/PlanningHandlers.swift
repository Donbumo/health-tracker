import Foundation

/// Queue handlers for offline planning (android `processPending` `planning_*` branches). The entity's
/// visible state follows the attempt: syncing → synced, pending on retryable errors, conflict otherwise.
public enum PlanningHandlers {
    public static let all: [String: PendingActionHandler] = [
        "planning_plan_create": Handler { action, _, api, _ in try await api.createPlan(try body(action), key: action.idempotencyKey) },
        "planning_plan_patch": Handler { action, _, api, _ in try await api.patchPlan(action.entityId, try body(action), key: action.idempotencyKey) },
        "planning_workout_create": Handler { action, _, api, _ in
            try await api.createPlanWorkout(planId: action.entityId, try body(action), key: action.idempotencyKey)
        },
        "planning_workout_patch": Handler { action, _, api, _ in try await api.patchPlanWorkout(action.entityId, try body(action), key: action.idempotencyKey) },
        "planning_schedule": Handler { action, scope, api, store in
            let root = try body(action)
            guard let workoutId = root["workout_id"]?.stringValue, let request = root["request"] else {
                throw AppFailure(.localStorageError, "La programación pendiente no puede recuperarse.", retryable: false)
            }
            let response = try await api.schedulePlanWorkout(workoutId, request, key: action.idempotencyKey)
            try await store.applyScheduleResult(scope, id: action.entityId, date: response.scheduledForDate, timezone: response.timezone,
                                                status: response.status, revision: response.revision)
        },
        "planning_schedule_patch": Handler { action, scope, api, store in
            let response = try await api.reschedulePlannedWorkout(action.entityId, try body(action), key: action.idempotencyKey)
            try await store.applyScheduleResult(scope, id: action.entityId, date: response.scheduledForDate, timezone: response.timezone,
                                                status: response.status, revision: response.revision)
        },
        "planning_cancel_schedule": Handler { action, scope, api, store in
            try await api.cancelScheduledWorkout(action.entityId, try body(action), key: action.idempotencyKey)
            try await store.deletePlanned(scope, id: action.entityId)
        },
    ]

    static func body(_ action: PendingAction) throws -> JSONValue {
        guard let value = try? JSONValue.parse(action.payloadJSON) else {
            throw AppFailure(.localStorageError, "La operación pendiente no puede recuperarse.", retryable: false)
        }
        return value
    }

    struct Handler: PendingActionHandler {
        let send: @Sendable (PendingAction, String, APIClient, LocalStore) async throws -> Void

        init(_ send: @escaping @Sendable (PendingAction, String, APIClient, LocalStore) async throws -> Void) {
            self.send = send
        }

        func handle(_ action: PendingAction, scope: String, api: APIClient, store: LocalStore) async throws {
            try await store.markPlanningSyncStatus(scope, action: action, status: "syncing")
            do {
                try await send(action, scope, api, store)
                if action.actionType != "planning_cancel_schedule" {
                    try await store.markPlanningSyncStatus(scope, action: action, status: "synced")
                }
            } catch let failure as AppFailure {
                if failure.retryable {
                    try await store.markPlanningSyncStatus(scope, action: action, status: "pending")
                } else {
                    try await recordConflict(action, failure: failure, scope: scope, api: api, store: store)
                    try await store.markPlanningSyncStatus(scope, action: action, status: "conflict")
                }
                throw failure
            }
        }

        /// Android `markPlanningConflict`: keep both names and revisions so the user can choose.
        private func recordConflict(_ action: PendingAction, failure: AppFailure, scope: String, api: APIClient, store: LocalStore) async throws {
            let entity = await store.planningEntity(scope, entityId: action.entityId)
            var remoteName: String?
            var remoteRevision: Int?
            switch entity {
            case .schedule:
                if let remote = try? await api.plannedWorkout(action.entityId) {
                    remoteName = "\(remote.title) · \(remote.scheduledForDate)"
                    remoteRevision = remote.revision
                }
            case .workout:
                if let remote = try? await api.planWorkout(action.entityId) { remoteName = remote.name; remoteRevision = remote.revision }
            case .plan:
                if let remote = try? await api.plan(action.entityId) { remoteName = remote.name; remoteRevision = remote.revision }
            case nil:
                return
            }
            let type: String = switch failure.serverCode {
            case "resource_archived": "archived_remote"
            case "not_found": "deleted_or_unavailable"
            case "active_schedules": "schedule_date_conflict"
            default: action.actionType == "planning_schedule_patch" ? "schedule_date_conflict" : "revision_conflict"
            }
            try await store.recordPlanningConflict(scope, entityId: action.entityId, conflictType: type, remoteName: remoteName, remoteRevision: remoteRevision)
        }
    }
}
