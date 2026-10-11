import Foundation

/// Live workout capture (android `CompanionRepository.downloadWorkout…completeWorkout`). Every local
/// change is persisted first; server operations travel through the strict FIFO queue.
public struct WorkoutRepository: Sendable {
    private let api: APIClient
    private let store: LocalStore
    private let now: @Sendable () -> Date
    private let newId: @Sendable () -> String

    public init(api: APIClient, store: LocalStore, now: @escaping @Sendable () -> Date = Date.init,
                newId: @escaping @Sendable () -> String = { UUID().uuidString.lowercased() }) {
        self.api = api
        self.store = store
        self.now = now
        self.newId = newId
    }

    /// Downloads and verifies the package for a planned workout and acknowledges it. A still-valid
    /// download is reused; a newer revision never replaces the package of an active draft.
    public func downloadWorkout(scope: String, plannedId: String) async throws -> String {
        guard let planned = await store.plannedWorkout(scope, id: plannedId) else {
            throw AppFailure(.localStorageError, "La programación no está disponible localmente.", retryable: false)
        }
        if ["locally_pending", "syncing"].contains(planned.status) {
            throw AppFailure(.localStorageError, "La programación aún no existe en el servidor. Sincroniza e inténtalo de nuevo.", retryable: true)
        }
        var stalePackageId: String?
        if let existing = await store.packageForPlanned(scope, plannedId: plannedId) {
            let notExpired = existing.expiresAt.flatMap(DisplayText.parseInstant).map { $0 > now() } ?? true
            if await store.delivery(scope, id: existing.deliveryId) != nil, existing.revision == planned.revision, notExpired {
                return existing.deliveryId
            }
            if let draft = await store.draft(scope, deliveryId: existing.deliveryId), !["completion_pending", "aborted_pending", "corrupt"].contains(draft.status) {
                try await store.recordPackageConflict(scope, plannedId: plannedId, package: existing, plannedTitle: planned.title,
                                                      plannedDate: planned.scheduledForDate, serverRevision: planned.revision, now: now())
                throw AppFailure(.revisionConflict, "Hay una versión más reciente, pero el entrenamiento activo conserva su descarga original.", retryable: false)
            }
            stalePackageId = existing.packageId
        }
        let delivery = try await api.createDelivery(plannedWorkoutId: plannedId, key: newId())
        let verified = try await api.downloadPackage(deliveryId: delivery.id)
        guard delivery.packageHash.lowercased() == verified.calculatedHash else {
            throw AppFailure(.packageHashMismatch, "La entrega y su package declaran hashes distintos.", retryable: false)
        }
        let ack = CompanionPayload.operation(id: newId(), baseRevision: delivery.revision,
                                             receivedAt: ISO8601DateFormatter().string(from: now()), packageHash: delivery.packageHash)
        let ackKey = newId()
        do {
            let acknowledged = try await api.transition(deliveryId: delivery.id, action: "ack", operation: ack, key: ackKey)
            try await store.storeDownloadedPackage(scope, delivery: acknowledged, package: verified, stalePackageId: stalePackageId, queuedAck: nil, now: now())
        } catch let failure as AppFailure where failure.retryable {
            try await store.storeDownloadedPackage(scope, delivery: delivery.with(status: "acknowledged_pending", revision: delivery.revision + 1),
                                                   package: verified, stalePackageId: stalePackageId, queuedAck: (ackKey, ack), now: now())
        }
        return delivery.id
    }

    /// Creates (or recovers and re-validates) the local draft for a downloaded delivery.
    public func startWorkout(scope: String, deliveryId: String, deviceId: String) async throws -> WorkoutDraft {
        if await store.draft(scope, deliveryId: deliveryId) == nil {
            _ = try await store.startDraft(scope, deliveryId: deliveryId,
                                           ids: DraftIdentifiers(clientSubmissionId: newId(), clientEventId: newId(), startOperationId: newId(), startKey: newId()),
                                           now: now())
        }
        guard let draft = try await store.validateDraft(scope, deliveryId: deliveryId, currentScope: scope, deviceId: deviceId, now: now()) else {
            throw AppFailure(.draftCorrupt, "No se encontró el borrador.", retryable: false)
        }
        if draft.status == "corrupt" {
            throw AppFailure(.draftCorrupt, "El borrador local no superó la validación de integridad.", retryable: false)
        }
        return draft
    }

    public func saveSet(scope: String, _ set: DraftSet) async throws {
        try await store.saveDraftSet(scope, set, now: now())
    }

    public func checkpointSet(scope: String, _ set: DraftSet) async throws -> Bool {
        try await store.checkpointDraftSet(scope, set, eventId: newId(), key: newId(), now: now())
    }

    public func duplicateSet(scope: String, _ set: DraftSet) async throws {
        try await store.duplicateDraftSet(scope, set, now: now())
    }

    public func updateSummary(scope: String, deliveryId: String, heartRate: Int?, calories: String?, notes: String?) async throws {
        try await store.updateDraftSummary(scope, deliveryId: deliveryId, heartRate: heartRate, calories: calories, notes: notes, now: now())
    }

    public func pauseOrResume(scope: String, deliveryId: String, pause: Bool) async throws -> Bool {
        try await store.pauseOrResume(scope, deliveryId: deliveryId, pause: pause, eventId: newId(), key: newId(), now: now())
    }

    public func abortWorkout(scope: String, deliveryId: String) async throws -> Bool {
        try await store.abortDraft(scope, deliveryId: deliveryId, operationId: newId(), key: newId(), now: now())
    }

    public func completeWorkout(scope: String, deliveryId: String) async throws -> Bool {
        try await store.completeDraft(scope, deliveryId: deliveryId, key: newId(), now: now())
    }

    public func discardCorruptDraft(scope: String, deliveryId: String) async throws {
        try await store.discardCorruptDraft(scope, deliveryId: deliveryId)
    }
}
