import Foundation

/// Queue handlers for the companion protocol (android `processPending` companion branches).
public enum CompanionHandlers {
    /// Handlers by action type, for `SyncEngine(handlers:)` so they exist before any queue drain.
    public static let all: [String: PendingActionHandler] = [
        "companion_ack": TransitionHandler(action: "ack"),
        "companion_start": TransitionHandler(action: "start"),
        "companion_abort": AbortHandler(),
        "companion_progress": ProgressHandler(),
        "companion_complete": CompleteHandler(),
    ]

    public static func register(on engine: SyncEngine) async {
        for (type, handler) in all { await engine.register(handler, for: type) }
    }

    static func payload(_ action: PendingAction) throws -> JSONValue {
        guard let value = try? JSONValue.parse(action.payloadJSON) else {
            throw AppFailure(.localStorageError, "La operación pendiente no puede recuperarse.", retryable: false)
        }
        return value
    }

    struct TransitionHandler: PendingActionHandler {
        let action: String

        func handle(_ pending: PendingAction, scope: String, api: APIClient, store: LocalStore) async throws {
            do {
                let delivery = try await api.transition(deliveryId: pending.entityId, action: action, operation: try payload(pending), key: pending.idempotencyKey)
                try await store.applyDelivery(scope, delivery)
            } catch let failure as AppFailure where action == "start" && failure.code == .revisionConflict {
                // The start may already be applied server-side (lost response): accept it only when compatible.
                guard try await reconcileStarted(pending.entityId, scope: scope, api: api, store: store) else { throw failure }
            }
        }

        private func reconcileStarted(_ deliveryId: String, scope: String, api: APIClient, store: LocalStore) async throws -> Bool {
            guard let remote = try await api.deliveries().first(where: { $0.id == deliveryId }),
                  let local = await store.delivery(scope, id: deliveryId),
                  let package = await store.packageForDelivery(scope, deliveryId: deliveryId),
                  let draft = await store.draft(scope, deliveryId: deliveryId) else { return false }
            let deviceId = await store.accountDeviceId(scope)
            let compatible = remote.status == "started" && remote.deviceId != nil && remote.deviceId == deviceId &&
                remote.profileId == local.profileId && remote.plannedWorkoutId == local.plannedWorkoutId &&
                remote.packageHash.lowercased() == local.packageHash.lowercased() &&
                remote.packageHash.lowercased() == package.packageHash.lowercased() &&
                package.packageId == draft.packageId && package.packageHash.lowercased() == draft.packageHash.lowercased()
            guard compatible else { return false }
            try await store.applyDelivery(scope, remote)
            return true
        }
    }

    struct AbortHandler: PendingActionHandler {
        func handle(_ pending: PendingAction, scope: String, api: APIClient, store: LocalStore) async throws {
            let delivery = try await api.transition(deliveryId: pending.entityId, action: "abort", operation: try payload(pending), key: pending.idempotencyKey)
            try await store.applyAbortConfirmed(scope, delivery)
        }
    }

    struct ProgressHandler: PendingActionHandler {
        func handle(_ pending: PendingAction, scope: String, api: APIClient, store: LocalStore) async throws {
            try await api.progress(deliveryId: pending.entityId, request: try payload(pending), key: pending.idempotencyKey)
        }
    }

    struct CompleteHandler: PendingActionHandler {
        func handle(_ pending: PendingAction, scope: String, api: APIClient, store: LocalStore) async throws {
            let response = try await api.complete(deliveryId: pending.entityId, request: try payload(pending), key: pending.idempotencyKey)
            try await store.applyCompletion(scope, deliveryId: pending.entityId, response)
        }
    }
}
