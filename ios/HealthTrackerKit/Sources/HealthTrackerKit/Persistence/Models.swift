import Foundation
import SwiftData

// SwiftData offline cache (android Room `CompanionDatabase` subset for Mobile Sync).
// Every row carries `accountScope`; `key` = scope + id keeps accounts and servers isolated.

func scopedKey(_ scope: String, _ id: String) -> String { "\(scope)|\(id)" }

@Model
final class AccountModel {
    @Attribute(.unique) var scope: String
    var serverURL: String
    var userPublicId: String
    var displayEmail: String
    var deviceId: String
    var timezone: String
    var createdAt: String

    init(_ record: AccountRecord) {
        scope = record.scope
        serverURL = record.serverURL
        userPublicId = record.userPublicId
        displayEmail = record.displayEmail
        deviceId = record.deviceId
        timezone = record.timezone
        createdAt = record.createdAt
    }

    var record: AccountRecord {
        AccountRecord(scope: scope, serverURL: serverURL, userPublicId: userPublicId, displayEmail: displayEmail,
                      deviceId: deviceId, timezone: timezone, createdAt: createdAt)
    }
}

@Model
final class SyncStateModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var deviceId: String
    var cursor: String
    var lastSyncAt: String?
    var lastServerTime: String?

    init(accountScope: String, deviceId: String, cursor: String, lastSyncAt: String?, lastServerTime: String?) {
        key = scopedKey(accountScope, deviceId)
        self.accountScope = accountScope
        self.deviceId = deviceId
        self.cursor = cursor
        self.lastSyncAt = lastSyncAt
        self.lastServerTime = lastServerTime
    }
}

@Model
final class PlannedWorkoutModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var id: String
    var planId: String
    var planVersionId: String
    var scheduledForDate: String
    var timezone: String
    var status: String
    var title: String
    var revision: Int
    var updatedAt: String
    var deleted: Bool
    var sourceWorkoutId: String?

    init(scope: String, dto: PlannedWorkoutDTO) {
        key = scopedKey(scope, dto.id)
        accountScope = scope
        id = dto.id
        planId = dto.trainingPlanId
        planVersionId = dto.trainingPlanVersionId
        scheduledForDate = dto.scheduledForDate
        timezone = dto.timezone
        status = dto.status
        title = dto.title
        revision = dto.revision
        updatedAt = dto.updatedAt
        deleted = dto.deleted
        sourceWorkoutId = dto.sourceWorkoutId
    }

    func update(from dto: PlannedWorkoutDTO) {
        planId = dto.trainingPlanId
        planVersionId = dto.trainingPlanVersionId
        scheduledForDate = dto.scheduledForDate
        timezone = dto.timezone
        status = dto.status
        title = dto.title
        revision = dto.revision
        updatedAt = dto.updatedAt
        deleted = dto.deleted
        sourceWorkoutId = dto.sourceWorkoutId
    }
}

@Model
final class DeliveryModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var id: String
    var plannedWorkoutId: String
    var profileId: String
    var packageHash: String
    var status: String
    var revision: Int
    var lastClientSequence: Int
    var expiresAt: String?
    var trainingSessionId: String?
    var updatedAt: String

    init(scope: String, dto: DeliveryDTO) {
        key = scopedKey(scope, dto.id)
        accountScope = scope
        id = dto.id
        plannedWorkoutId = dto.plannedWorkoutId
        profileId = dto.profileId
        packageHash = dto.packageHash
        status = dto.status
        revision = dto.revision
        lastClientSequence = dto.lastClientSequence
        expiresAt = dto.expiresAt
        trainingSessionId = dto.trainingSessionId
        updatedAt = dto.updatedAt
    }

    func update(from dto: DeliveryDTO) {
        plannedWorkoutId = dto.plannedWorkoutId
        profileId = dto.profileId
        packageHash = dto.packageHash
        status = dto.status
        revision = dto.revision
        lastClientSequence = dto.lastClientSequence
        expiresAt = dto.expiresAt
        trainingSessionId = dto.trainingSessionId
        updatedAt = dto.updatedAt
    }
}

@Model
final class LocalProfileModel {
    @Attribute(.unique) var accountScope: String
    var profileId: String?
    var protocolVersion: String?
    var workoutSchemaVersion: String?
    var resultSchemaVersion: String?
    var revision: Int?
    var negotiatedAt: String?

    init(scope: String) { accountScope = scope }

    func update(from dto: CompanionProfileDTO) {
        profileId = dto.id
        protocolVersion = dto.protocolVersion
        workoutSchemaVersion = dto.workoutSchemaVersion
        resultSchemaVersion = dto.resultSchemaVersion
        revision = dto.revision
        negotiatedAt = dto.lastNegotiatedAt
    }
}

@Model
final class RecentSessionModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var id: String
    var clientEventId: String
    var plannedWorkoutId: String?
    var title: String
    var completedAt: String
    var durationSeconds: Int?
    var exerciseCount: Int
    var setCount: Int
    var totalLoadKg: String
    var origin: String
    var syncStatus: String
    var summary: String

    init(scope: String, id: String) {
        key = scopedKey(scope, id)
        accountScope = scope
        self.id = id
        clientEventId = id
        title = ""
        completedAt = ""
        exerciseCount = 0
        setCount = 0
        totalLoadKg = "0"
        origin = ""
        syncStatus = "synced"
        summary = ""
    }
}

@Model
final class PendingActionModel {
    @Attribute(.unique) var key: String
    /// Monotonic per-store sequence; the queue is strict FIFO by this value.
    var sequence: Int64
    var accountScope: String
    var actionType: String
    var entityId: String
    var idempotencyKey: String
    var payloadJSON: String
    var payloadHash: String
    var status: String
    var attemptCount: Int
    var notBefore: Date
    var createdAt: String
    var lastErrorCode: String?

    init(sequence: Int64, scope: String, actionType: String, entityId: String, idempotencyKey: String,
         payloadJSON: String, payloadHash: String, createdAt: String) {
        key = scopedKey(scope, idempotencyKey)
        self.sequence = sequence
        accountScope = scope
        self.actionType = actionType
        self.entityId = entityId
        self.idempotencyKey = idempotencyKey
        self.payloadJSON = payloadJSON
        self.payloadHash = payloadHash
        status = "pending"
        attemptCount = 0
        notBefore = .distantPast
        self.createdAt = createdAt
    }
}

@Model
final class PlanningConflictModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var entityId: String
    var entityType: String
    var localRevision: Int
    var serverRevision: Int?
    var changedFields: String
    var localName: String?
    var remoteName: String?
    var createdAt: String

    init(scope: String, entityId: String, entityType: String, localRevision: Int, serverRevision: Int?,
         changedFields: String, localName: String?, remoteName: String?, createdAt: String) {
        key = scopedKey(scope, entityId)
        accountScope = scope
        self.entityId = entityId
        self.entityType = entityType
        self.localRevision = localRevision
        self.serverRevision = serverRevision
        self.changedFields = changedFields
        self.localName = localName
        self.remoteName = remoteName
        self.createdAt = createdAt
    }
}

enum LocalSchema {
    static let models: [any PersistentModel.Type] = [
        AccountModel.self, SyncStateModel.self, PlannedWorkoutModel.self, DeliveryModel.self,
        LocalProfileModel.self, RecentSessionModel.self, PendingActionModel.self, PlanningConflictModel.self,
        HistorySessionModel.self, HistoryExerciseModel.self, HistorySetModel.self, HistoryPageModel.self,
        HistoryQueryStateModel.self, ProgressSummaryModel.self, ProgressExerciseModel.self, ProgressPointModel.self,
        PersonalRecordModel.self, PlanModel.self, PlanWorkoutModel.self, PlanExerciseModel.self, PlanSetModel.self,
    ]
}
