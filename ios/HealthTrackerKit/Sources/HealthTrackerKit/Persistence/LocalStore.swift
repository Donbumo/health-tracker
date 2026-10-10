import Foundation
import SwiftData

// MARK: Sendable snapshots for UI and services

public struct PlannedWorkout: Sendable, Equatable, Identifiable {
    public let id: String
    public let title: String
    public let scheduledForDate: String
    public let timezone: String
    public let status: String
    public let revision: Int
    public let planId: String
    public let sourceWorkoutId: String?
}

public struct RecentSession: Sendable, Equatable, Identifiable {
    public let id: String
    public let title: String
    public let completedAt: String
    public let durationSeconds: Int?
    public let exerciseCount: Int
    public let setCount: Int
    public let totalLoadKg: String
    public let origin: String
    public let syncStatus: String
    public let summary: String
}

public struct PendingAction: Sendable, Equatable {
    public let key: String
    public let sequence: Int64
    public let actionType: String
    public let entityId: String
    public let idempotencyKey: String
    public let payloadJSON: String
    public let status: String
    public let attemptCount: Int
    public let notBefore: Date
    public let lastErrorCode: String?
}

public struct SyncSnapshot: Sendable, Equatable {
    public let pendingCount: Int
    public let conflictCount: Int
    public let hasSyncState: Bool

    public init(pendingCount: Int, conflictCount: Int, hasSyncState: Bool) {
        self.pendingCount = pendingCount
        self.conflictCount = conflictCount
        self.hasSyncState = hasSyncState
    }
}

/// Owns the SwiftData context. Each public write runs as one unit: saved on success, rolled back on error.
@ModelActor
public actor LocalStore: AccountStore {
    public static func make(inMemory: Bool = false, url: URL? = nil) throws -> LocalStore {
        let schema = Schema(LocalSchema.models)
        let configuration: ModelConfiguration
        if inMemory {
            configuration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: true)
        } else if let url {
            configuration = ModelConfiguration(schema: schema, url: url)
        } else {
            configuration = ModelConfiguration("companion_v1", schema: schema)
        }
        let container = try ModelContainer(for: schema, configurations: [configuration])
        return LocalStore(modelContainer: container)
    }

    func write<T>(_ body: () throws -> T) throws -> T {
        do {
            let result = try body()
            try modelContext.save()
            return result
        } catch {
            modelContext.rollback()
            if error is AppFailure { throw error }
            throw AppFailure(.localStorageError, "No fue posible guardar los datos locales.", retryable: true)
        }
    }

    func fetch<M: PersistentModel>(_ predicate: Predicate<M>, sort: [SortDescriptor<M>] = [], limit: Int? = nil) throws -> [M] {
        var descriptor = FetchDescriptor<M>(predicate: predicate, sortBy: sort)
        descriptor.fetchLimit = limit
        return try modelContext.fetch(descriptor)
    }

    // MARK: AccountStore

    public func account(_ scope: String) async -> AccountRecord? {
        try? fetch(#Predicate<AccountModel> { $0.scope == scope }).first?.record
    }

    public func upsert(_ account: AccountRecord) async throws {
        try write {
            let scope = account.scope
            try fetch(#Predicate<AccountModel> { $0.scope == scope }).forEach(modelContext.delete)
            modelContext.insert(AccountModel(account))
        }
    }

    /// Deletes every cached row for the account (logout, revoke, clear local).
    public func clearAccountData(_ scope: String) async throws {
        try write {
            try modelContext.delete(model: AccountModel.self, where: #Predicate { $0.scope == scope })
            try modelContext.delete(model: SyncStateModel.self, where: #Predicate { $0.accountScope == scope })
            try modelContext.delete(model: PlannedWorkoutModel.self, where: #Predicate { $0.accountScope == scope })
            try modelContext.delete(model: DeliveryModel.self, where: #Predicate { $0.accountScope == scope })
            try modelContext.delete(model: LocalProfileModel.self, where: #Predicate { $0.accountScope == scope })
            try modelContext.delete(model: RecentSessionModel.self, where: #Predicate { $0.accountScope == scope })
            try modelContext.delete(model: PendingActionModel.self, where: #Predicate { $0.accountScope == scope })
            try modelContext.delete(model: PlanningConflictModel.self, where: #Predicate { $0.accountScope == scope })
            try clearTrainingData(scope)
            try clearWorkoutData(scope)
        }
    }

    // MARK: Sync state

    public func syncCursor(_ scope: String) -> String? {
        try? fetch(#Predicate<SyncStateModel> { $0.accountScope == scope }).first?.cursor
    }

    // MARK: Bootstrap and pull

    /// Applies a verified bootstrap (plus an optional fresh negotiation) atomically.
    public func applyBootstrap(_ scope: String, _ value: BootstrapResponse, negotiated: CompanionProfileDTO? = nil, now: Date = Date()) throws {
        try write {
            let protectedIds = try protectedScheduleIds(scope)
            for remote in value.plannedWorkouts {
                try applyPlanned(scope, remote, protected: protectedIds.contains(remote.id), now: now)
            }
            for delivery in value.companion.deliveries { try upsertDelivery(scope, delivery) }
            if let profile = value.companion.profile { try upsertProfile(scope, profile) }
            if let negotiated { try upsertProfile(scope, negotiated) }
            for completed in value.completedWorkouts { try upsertRecent(scope, completed) }
            try setSyncState(scope, deviceId: value.device.deviceId, cursor: value.cursor, serverTime: value.serverTime, now: now)
        }
    }

    public func upsertProfile(_ scope: String, _ profile: CompanionProfileDTO) throws {
        let existing = try fetch(#Predicate<LocalProfileModel> { $0.accountScope == scope }).first
        let model = existing ?? LocalProfileModel(scope: scope)
        if existing == nil { modelContext.insert(model) }
        model.update(from: profile)
    }

    public func saveProfile(_ scope: String, _ profile: CompanionProfileDTO) throws {
        try write { try upsertProfile(scope, profile) }
    }

    /// Applies one pull page and advances the cursor in the same unit.
    public func applyPullPage(_ scope: String, _ page: PullResponse, deviceId: String, now: Date = Date()) throws {
        try write {
            let protectedIds = try protectedScheduleIds(scope)
            for change in page.changes {
                try applyChange(scope, change, protectedIds: protectedIds, now: now)
            }
            try setSyncState(scope, deviceId: deviceId, cursor: page.nextCursor, serverTime: page.serverTime, now: now)
        }
    }

    private func applyChange(_ scope: String, _ change: SyncChangeDTO, protectedIds: Set<String>, now: Date) throws {
        if change.operation == "delete" {
            if change.entityType == "planned_workout" {
                let key = scopedKey(scope, change.entityId)
                try modelContext.delete(model: PlannedWorkoutModel.self, where: #Predicate { $0.key == key })
            }
            return
        }
        do {
            switch change.entityType {
            case "planned_workout":
                if let remote = try change.decodePayload(PlannedWorkoutDTO.self) {
                    try applyPlanned(scope, remote, protected: protectedIds.contains(remote.id), now: now, requireLocalPendingState: true)
                }
            case "completed_workout":
                if let completed = try change.decodePayload(CompletedWorkoutDTO.self) { try upsertRecent(scope, completed) }
            case "companion_delivery":
                if let delivery = try change.decodePayload(DeliveryDTO.self) { try upsertDelivery(scope, delivery) }
            case "companion_profile":
                if let profile = try change.decodePayload(CompanionProfileDTO.self) { try upsertProfile(scope, profile) }
            default:
                // training_plan and later entity types are refreshed by their own feature stages.
                break
            }
        } catch is DecodingError {
            throw AppFailure(.schemaIncompatible, "El servidor respondió con un contrato incompatible.", retryable: false)
        }
    }

    /// Remote schedule changes never overwrite a local schedule edit that is still queued: they become conflicts.
    private func applyPlanned(_ scope: String, _ remote: PlannedWorkoutDTO, protected: Bool, now: Date, requireLocalPendingState: Bool = false) throws {
        let key = scopedKey(scope, remote.id)
        let local = try fetch(#Predicate<PlannedWorkoutModel> { $0.key == key }).first
        let localPending = !requireLocalPendingState || ["locally_pending", "syncing", "conflict", "cancelled"].contains(local?.status ?? "")
        if let local, protected, localPending {
            try upsertConflict(PlanningConflictModel(
                scope: scope, entityId: remote.id, entityType: "schedule",
                localRevision: local.revision, serverRevision: remote.revision,
                changedFields: local.scheduledForDate != remote.scheduledForDate ? "schedule_date_conflict:scheduled_for_date" : "revision_conflict:revision",
                localName: "\(local.title) · \(local.scheduledForDate)",
                remoteName: "\(remote.title) · \(remote.scheduledForDate)",
                createdAt: iso(now)
            ))
            local.status = "conflict"
        } else if let local {
            local.update(from: remote)
        } else {
            modelContext.insert(PlannedWorkoutModel(scope: scope, dto: remote))
        }
    }

    private func protectedScheduleIds(_ scope: String) throws -> Set<String> {
        let types = ["planning_schedule", "planning_schedule_patch", "planning_cancel_schedule"]
        return Set(try fetch(#Predicate<PendingActionModel> { $0.accountScope == scope && types.contains($0.actionType) }).map(\.entityId))
    }

    private func upsertConflict(_ conflict: PlanningConflictModel) throws {
        let key = conflict.key
        try modelContext.delete(model: PlanningConflictModel.self, where: #Predicate { $0.key == key })
        modelContext.insert(conflict)
    }

    func upsertDelivery(_ scope: String, _ dto: DeliveryDTO) throws {
        let key = scopedKey(scope, dto.id)
        if let existing = try fetch(#Predicate<DeliveryModel> { $0.key == key }).first {
            existing.update(from: dto)
        } else {
            modelContext.insert(DeliveryModel(scope: scope, dto: dto))
        }
    }

    func upsertRecent(_ scope: String, _ completed: CompletedWorkoutDTO) throws {
        guard let id = completed.id ?? completed.clientEventId else {
            throw AppFailure(.schemaIncompatible, "El entrenamiento no contiene un identificador.", retryable: false)
        }
        let key = scopedKey(scope, id)
        let model = try fetch(#Predicate<RecentSessionModel> { $0.key == key }).first ?? {
            let created = RecentSessionModel(scope: scope, id: id)
            modelContext.insert(created)
            return created
        }()
        let sets = completed.exercises.flatMap(\.sets)
        let total = sets.compactMap(\.traditionalVolume).reduce(Decimal(0), +)
        model.clientEventId = completed.clientEventId ?? id
        model.plannedWorkoutId = completed.plannedWorkoutId
        model.title = "Entrenamiento"
        model.completedAt = completed.completedAt
        model.durationSeconds = completed.durationSeconds
        model.exerciseCount = completed.exercises.count
        model.setCount = sets.count
        model.totalLoadKg = Self.plain(total)
        model.origin = "Servidor"
        model.syncStatus = "synced"
        model.summary = String(completed.exercises.map(\.name).joined(separator: ", ").prefix(500))
    }

    private func setSyncState(_ scope: String, deviceId: String, cursor: String, serverTime: String, now: Date) throws {
        try modelContext.delete(model: SyncStateModel.self, where: #Predicate { $0.accountScope == scope })
        modelContext.insert(SyncStateModel(accountScope: scope, deviceId: deviceId, cursor: cursor, lastSyncAt: iso(now), lastServerTime: serverTime))
    }

    // MARK: Pending queue

    /// Inserts a durable operation. Re-enqueueing the same key with the same content is a no-op;
    /// a different payload under the same key is rejected.
    public func enqueue(_ scope: String, actionType: String, entityId: String, idempotencyKey: String, payloadJSON: String, now: Date = Date()) throws {
        try write { try insertPending(scope, actionType: actionType, entityId: entityId, idempotencyKey: idempotencyKey, payloadJSON: payloadJSON, now: now) }
    }

    /// Queue insert for use inside a larger `write` unit.
    func insertPending(_ scope: String, actionType: String, entityId: String, idempotencyKey: String, payloadJSON: String, now: Date) throws {
        guard let payload = try? JSONValue.parse(payloadJSON) else {
            throw AppFailure(.localStorageError, "La operación pendiente no es JSON válido.", retryable: false)
        }
        let hash = CanonicalJSON.sha256(payload)
        let key = scopedKey(scope, idempotencyKey)
        if let existing = try fetch(#Predicate<PendingActionModel> { $0.key == key }).first {
            guard existing.payloadHash == hash, existing.actionType == actionType, existing.entityId == entityId else {
                throw AppFailure(.submissionConflict, "La clave idempotente ya pertenece a otra operación local.", retryable: false)
            }
            return
        }
        let last = try fetch(#Predicate<PendingActionModel> { _ in true }, sort: [SortDescriptor(\.sequence, order: .reverse)], limit: 1).first
        modelContext.insert(PendingActionModel(
            sequence: (last?.sequence ?? 0) + 1, scope: scope, actionType: actionType, entityId: entityId,
            idempotencyKey: idempotencyKey, payloadJSON: payloadJSON, payloadHash: hash, createdAt: iso(now)
        ))
    }

    public func headOfQueue(_ scope: String) -> PendingAction? {
        guard let model = try? fetch(
            #Predicate<PendingActionModel> { $0.accountScope == scope },
            sort: [SortDescriptor(\.sequence)], limit: 1
        ).first else { return nil }
        return PendingAction(
            key: model.key, sequence: model.sequence, actionType: model.actionType, entityId: model.entityId,
            idempotencyKey: model.idempotencyKey, payloadJSON: model.payloadJSON, status: model.status,
            attemptCount: model.attemptCount, notBefore: model.notBefore, lastErrorCode: model.lastErrorCode
        )
    }

    public func completePending(_ key: String) throws {
        try write { try modelContext.delete(model: PendingActionModel.self, where: #Predicate { $0.key == key }) }
    }

    public func reschedulePending(_ key: String, errorCode: String, notBefore: Date) throws {
        try write {
            guard let model = try fetch(#Predicate<PendingActionModel> { $0.key == key }).first else { return }
            model.status = "pending"
            model.attemptCount += 1
            model.lastErrorCode = errorCode
            model.notBefore = notBefore
        }
    }

    public func markPendingConflict(_ key: String, errorCode: String) throws {
        try write {
            guard let model = try fetch(#Predicate<PendingActionModel> { $0.key == key }).first else { return }
            model.status = "conflict"
            model.attemptCount += 1
            model.lastErrorCode = errorCode
            model.notBefore = .distantFuture
        }
    }

    // MARK: Reads

    public func snapshot(_ scope: String) -> SyncSnapshot {
        let pending = (try? modelContext.fetchCount(FetchDescriptor<PendingActionModel>(predicate: #Predicate { $0.accountScope == scope }))) ?? 0
        let queueConflicts = (try? modelContext.fetchCount(FetchDescriptor<PendingActionModel>(predicate: #Predicate { $0.accountScope == scope && $0.status == "conflict" }))) ?? 0
        let planningConflicts = (try? modelContext.fetchCount(FetchDescriptor<PlanningConflictModel>(predicate: #Predicate { $0.accountScope == scope }))) ?? 0
        return SyncSnapshot(pendingCount: pending, conflictCount: queueConflicts + planningConflicts, hasSyncState: syncCursor(scope) != nil)
    }

    public func plannedWorkouts(_ scope: String) -> [PlannedWorkout] {
        let rows = (try? fetch(#Predicate<PlannedWorkoutModel> { $0.accountScope == scope && !$0.deleted }, sort: [SortDescriptor(\.scheduledForDate)])) ?? []
        return rows.map {
            PlannedWorkout(id: $0.id, title: $0.title, scheduledForDate: $0.scheduledForDate, timezone: $0.timezone,
                           status: $0.status, revision: $0.revision, planId: $0.planId, sourceWorkoutId: $0.sourceWorkoutId)
        }
    }

    public func recentSessions(_ scope: String, limit: Int = 30) -> [RecentSession] {
        let rows = (try? fetch(#Predicate<RecentSessionModel> { $0.accountScope == scope }, sort: [SortDescriptor(\.completedAt, order: .reverse)], limit: limit)) ?? []
        return rows.map {
            RecentSession(id: $0.id, title: $0.title, completedAt: $0.completedAt, durationSeconds: $0.durationSeconds,
                          exerciseCount: $0.exerciseCount, setCount: $0.setCount, totalLoadKg: $0.totalLoadKg,
                          origin: $0.origin, syncStatus: $0.syncStatus, summary: $0.summary)
        }
    }

    public func deliveryCount(_ scope: String) -> Int {
        (try? modelContext.fetchCount(FetchDescriptor<DeliveryModel>(predicate: #Predicate { $0.accountScope == scope }))) ?? 0
    }

    public func localProfileRevision(_ scope: String) -> Int? {
        (try? fetch(#Predicate<LocalProfileModel> { $0.accountScope == scope }).first)?.revision
    }

    // MARK: Helpers

    func iso(_ date: Date) -> String { ISO8601DateFormatter().string(from: date) }

    /// Plain decimal text without trailing zeros (Kotlin `stripTrailingZeros().toPlainString()`).
    static func plain(_ value: Decimal) -> String {
        NSDecimalNumber(decimal: value).stringValue
    }
}
