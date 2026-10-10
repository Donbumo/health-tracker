import Foundation
import SwiftData

// History, progress and planning cache (android Room `history_*`, `progress_*`, `personal_records`,
// `mobile_plan*`). Same isolation rule as the sync cache: every row carries `accountScope`.

@Model
final class HistorySessionModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var publicId: String
    var clientEventId: String
    var plannedWorkoutId: String?
    var trainingPlanId: String?
    var trainingPlanVersionId: String?
    var name: String
    var performedAt: String
    var startedAt: String?
    var completedAt: String
    var timezone: String
    var durationSeconds: Int?
    var exerciseCount: Int
    var setCount: Int
    var volumeKg: String?
    var volumePartial: Bool
    var source: String
    var syncStatus: String
    var notes: String?
    var detailCached: Bool
    var updatedAt: String

    init(scope: String, publicId: String, clientEventId: String) {
        key = scopedKey(scope, publicId)
        accountScope = scope
        self.publicId = publicId
        self.clientEventId = clientEventId
        name = ""
        performedAt = ""
        completedAt = ""
        timezone = "UTC"
        exerciseCount = 0
        setCount = 0
        volumePartial = false
        source = ""
        syncStatus = "synced"
        detailCached = false
        updatedAt = ""
    }
}

@Model
final class HistoryExerciseModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var sessionPublicId: String
    var exerciseOrder: Int
    var exercisePublicId: String?
    var name: String
    var notes: String?

    init(scope: String, sessionPublicId: String, exerciseOrder: Int, exercisePublicId: String?, name: String, notes: String?) {
        key = scopedKey(scope, "\(sessionPublicId)#\(exerciseOrder)")
        accountScope = scope
        self.sessionPublicId = sessionPublicId
        self.exerciseOrder = exerciseOrder
        self.exercisePublicId = exercisePublicId
        self.name = name
        self.notes = notes
    }
}

@Model
final class HistorySetModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var sessionPublicId: String
    var exerciseOrder: Int
    var setNumber: Int
    var weightKg: String?
    var displayValue: String?
    var displayUnit: String?
    var loadMode: String
    var reps: Int
    var rir: String?
    var rpe: String?
    var restSeconds: Int?
    var durationSeconds: String?
    var distanceMeters: String?
    var notes: String?

    init(scope: String, sessionPublicId: String, exerciseOrder: Int, setNumber: Int, loadMode: String, reps: Int) {
        key = scopedKey(scope, "\(sessionPublicId)#\(exerciseOrder)#\(setNumber)")
        accountScope = scope
        self.sessionPublicId = sessionPublicId
        self.exerciseOrder = exerciseOrder
        self.setNumber = setNumber
        self.loadMode = loadMode
        self.reps = reps
    }
}

/// Position of a session inside one filtered history listing.
@Model
final class HistoryPageModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var cacheKey: String
    var sessionPublicId: String
    var position: Int

    init(scope: String, cacheKey: String, sessionPublicId: String, position: Int) {
        key = scopedKey(scope, "\(cacheKey)#\(sessionPublicId)")
        accountScope = scope
        self.cacheKey = cacheKey
        self.sessionPublicId = sessionPublicId
        self.position = position
    }
}

@Model
final class HistoryQueryStateModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var cacheKey: String
    var nextCursor: String?
    var hasMore: Bool
    var updatedAt: String

    init(scope: String, cacheKey: String, nextCursor: String?, hasMore: Bool, updatedAt: String) {
        key = scopedKey(scope, cacheKey)
        accountScope = scope
        self.cacheKey = cacheKey
        self.nextCursor = nextCursor
        self.hasMore = hasMore
        self.updatedAt = updatedAt
    }
}

@Model
final class ProgressSummaryModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var range: String
    var sessions: Int
    var trainingDays: Int
    var distinctExercises: Int
    var completedSets: Int
    var totalReps: Int
    var volumeKg: String?
    var volumePartial: Bool
    var durationSeconds: Int
    var hasComparison: Bool
    var updatedAt: String

    init(scope: String, dto: ProgressSummaryDTO, now: String) {
        key = scopedKey(scope, dto.range)
        accountScope = scope
        range = dto.range
        sessions = dto.metrics.sessions
        trainingDays = dto.metrics.trainingDays
        distinctExercises = dto.metrics.distinctExercises
        completedSets = dto.metrics.completedSets
        totalReps = dto.metrics.totalReps
        volumeKg = dto.metrics.volumeKg
        volumePartial = dto.metrics.volumePartial
        durationSeconds = dto.metrics.durationSeconds
        hasComparison = !(dto.comparison?.isEmpty ?? true)
        updatedAt = now
    }
}

@Model
final class ProgressExerciseModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var range: String
    var publicId: String
    var name: String
    var lastPerformedAt: String?
    var sessionCount: Int
    var setCount: Int
    var bestLoadKg: String?
    var bestReps: Int?
    var bestRepsWeightKg: String?
    var volumeKg: String?
    var volumePartial: Bool
    var loadComparable: Bool
    var loadModes: String
    var trend: String
    var updatedAt: String

    init(scope: String, range: String, dto: ProgressExerciseDTO, now: String) {
        key = scopedKey(scope, "\(range)#\(dto.publicId)")
        accountScope = scope
        self.range = range
        publicId = dto.publicId
        name = dto.name
        lastPerformedAt = dto.lastPerformedAt
        sessionCount = dto.sessionCount
        setCount = dto.setCount
        bestLoadKg = dto.bestLoadKg
        bestReps = dto.bestRepetitionSet?.reps
        bestRepsWeightKg = dto.bestRepetitionSet?.weightKg
        volumeKg = dto.volumeKg
        volumePartial = dto.volumePartial
        loadComparable = dto.loadComparable
        loadModes = dto.loadModes.joined(separator: "|")
        trend = dto.trend
        updatedAt = now
    }
}

@Model
final class ProgressPointModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var range: String
    var exercisePublicId: String
    var sessionPublicId: String
    var date: String
    var performedAt: String
    var bestLoadKg: String?
    var bestReps: Int?
    var volumeKg: String?
    var setCount: Int
    var averageRir: String?
    var averageRpe: String?
    var loadComparable: Bool

    init(scope: String, range: String, exercisePublicId: String, dto: ProgressPointDTO) {
        key = scopedKey(scope, "\(range)#\(exercisePublicId)#\(dto.sessionPublicId)")
        accountScope = scope
        self.range = range
        self.exercisePublicId = exercisePublicId
        sessionPublicId = dto.sessionPublicId
        date = dto.date
        performedAt = dto.performedAt
        bestLoadKg = dto.bestLoadKg
        bestReps = dto.bestReps
        volumeKg = dto.volumeKg
        setCount = dto.setCount
        averageRir = dto.averageRir
        averageRpe = dto.averageRpe
        loadComparable = dto.loadComparable
    }
}

@Model
final class PersonalRecordModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var range: String
    var exercisePublicId: String
    var type: String
    var value: String
    var unit: String
    var date: String
    var sessionPublicId: String
    var setIndex: Int?

    init(scope: String, range: String, exercisePublicId: String, dto: PersonalRecordDTO) {
        key = scopedKey(scope, "\(range)#\(exercisePublicId)#\(dto.type)")
        accountScope = scope
        self.range = range
        self.exercisePublicId = exercisePublicId
        type = dto.type
        value = dto.value
        unit = dto.unit
        date = dto.date
        sessionPublicId = dto.sessionPublicId
        setIndex = dto.setIndex
    }
}

@Model
final class PlanModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var publicId: String
    var name: String
    var planDescription: String?
    var status: String
    var revision: Int
    var activeVersionId: String?
    var activeVersion: Int?
    var workoutCount: Int
    /// `synced`, `pending`, `syncing` or `conflict` (Android `MobilePlanEntity.syncStatus`).
    var syncStatus: String
    var createdAt: String
    var updatedAt: String
    var archivedAt: String?

    init(scope: String, publicId: String) {
        key = scopedKey(scope, publicId)
        accountScope = scope
        self.publicId = publicId
        name = ""
        status = "active"
        revision = 0
        workoutCount = 0
        syncStatus = "synced"
        createdAt = ""
        updatedAt = ""
    }

    func update(from dto: MobilePlanDTO, syncStatus: String) {
        name = dto.name
        planDescription = dto.description
        status = dto.status
        revision = dto.revision
        activeVersionId = dto.activeVersionId
        activeVersion = dto.activeVersion
        workoutCount = dto.workoutCount
        self.syncStatus = syncStatus
        createdAt = dto.createdAt
        updatedAt = dto.updatedAt
        archivedAt = dto.archivedAt
    }
}

@Model
final class PlanWorkoutModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var publicId: String
    var planPublicId: String
    var name: String
    var notes: String?
    var position: Int
    var estimatedDurationSeconds: Int?
    var revision: Int
    var syncStatus: String
    var createdAt: String
    var updatedAt: String

    init(scope: String, planPublicId: String, dto: MobilePlanWorkoutDTO) {
        key = scopedKey(scope, dto.publicId)
        accountScope = scope
        publicId = dto.publicId
        self.planPublicId = planPublicId
        name = dto.name
        notes = dto.notes
        position = dto.position
        estimatedDurationSeconds = dto.estimatedDurationSeconds
        revision = dto.revision
        syncStatus = "synced"
        createdAt = dto.createdAt
        updatedAt = dto.updatedAt
    }

    /// A workout created on this device, pending its first sync.
    init(scope: String, planPublicId: String, publicId: String, name: String, notes: String?, position: Int, now: String) {
        key = scopedKey(scope, publicId)
        accountScope = scope
        self.publicId = publicId
        self.planPublicId = planPublicId
        self.name = name
        self.notes = notes
        self.position = position
        revision = 1
        syncStatus = "pending"
        createdAt = now
        updatedAt = now
    }
}

@Model
final class PlanExerciseModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var workoutPublicId: String
    var id: String
    var exerciseId: String?
    var name: String
    var notes: String?
    var exerciseOrder: Int

    init(scope: String, workoutPublicId: String, dto: MobilePlanExerciseDTO) {
        key = scopedKey(scope, "\(workoutPublicId)#\(dto.id)")
        accountScope = scope
        self.workoutPublicId = workoutPublicId
        id = dto.id
        exerciseId = dto.exerciseId
        name = dto.name
        notes = dto.notes
        exerciseOrder = dto.exerciseOrder
    }

    init(scope: String, workoutPublicId: String, value: PlanExercise) {
        key = scopedKey(scope, "\(workoutPublicId)#\(value.id)")
        accountScope = scope
        self.workoutPublicId = workoutPublicId
        id = value.id
        exerciseId = value.exerciseId
        name = value.name
        notes = value.notes
        exerciseOrder = value.exerciseOrder
    }
}

@Model
final class PlanSetModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var workoutPublicId: String
    var exerciseRowId: String
    var id: String
    var setNumber: Int
    var reps: Int?
    var repsMin: Int?
    var repsMax: Int?
    var weightKg: String?
    var loadValue: String?
    var loadUnit: String
    var loadMode: String
    var loadDetailsJSON: String?
    var rir: String?
    var rpe: String?
    var restSeconds: Int?
    var durationSeconds: Int?
    var distanceMeters: String?
    var notes: String?

    init(scope: String, workoutPublicId: String, exerciseRowId: String, dto: MobilePlanSetDTO) {
        key = scopedKey(scope, "\(workoutPublicId)#\(exerciseRowId)#\(dto.id)")
        accountScope = scope
        self.workoutPublicId = workoutPublicId
        self.exerciseRowId = exerciseRowId
        id = dto.id
        setNumber = dto.setNumber
        reps = dto.reps
        repsMin = dto.repsMin
        repsMax = dto.repsMax
        weightKg = dto.weightKg
        loadValue = dto.loadValue
        loadUnit = dto.loadUnit
        loadMode = dto.loadMode
        loadDetailsJSON = dto.loadDetails?.encoded()
        rir = dto.rir
        rpe = dto.rpe
        restSeconds = dto.restSeconds
        durationSeconds = dto.durationSeconds
        distanceMeters = dto.distanceMeters
        notes = dto.notes
    }

    init(scope: String, workoutPublicId: String, exerciseRowId: String, value: PlanSet) {
        key = scopedKey(scope, "\(workoutPublicId)#\(exerciseRowId)#\(value.id)")
        accountScope = scope
        self.workoutPublicId = workoutPublicId
        self.exerciseRowId = exerciseRowId
        id = value.id
        setNumber = value.setNumber
        reps = value.reps
        repsMin = value.repsMin
        repsMax = value.repsMax
        weightKg = value.weightKg
        loadValue = value.loadValue
        loadUnit = value.loadUnit
        loadMode = value.loadMode
        loadDetailsJSON = value.loadDetailsJSON
        rir = value.rir
        rpe = value.rpe
        restSeconds = value.restSeconds
        durationSeconds = value.durationSeconds
        distanceMeters = value.distanceMeters
        notes = value.notes
    }
}

@Model
final class ExerciseCatalogModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var publicId: String
    var name: String
    var normalizedName: String
    var aliases: String
    var selectable: Bool
    var archived: Bool
    var preferredLoadMode: String?
    var preferredUnit: String?
    var updatedAt: String

    init(scope: String, dto: ExerciseCatalogItemDTO, now: String) {
        key = scopedKey(scope, dto.publicId)
        accountScope = scope
        publicId = dto.publicId
        name = dto.name
        normalizedName = dto.name.lowercased()
        aliases = dto.aliases.joined(separator: "|")
        selectable = dto.selectable
        archived = dto.archived
        preferredLoadMode = dto.preferredLoadMode
        preferredUnit = dto.preferredUnit
        updatedAt = now
    }
}

@Model
final class CatalogQueryStateModel {
    @Attribute(.unique) var key: String
    var accountScope: String
    var query: String
    var nextCursor: String?
    var hasMore: Bool
    var updatedAt: String

    init(scope: String, query: String, nextCursor: String?, hasMore: Bool, updatedAt: String) {
        key = scopedKey(scope, "catalog#\(query)")
        accountScope = scope
        self.query = query
        self.nextCursor = nextCursor
        self.hasMore = hasMore
        self.updatedAt = updatedAt
    }
}
